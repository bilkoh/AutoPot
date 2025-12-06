# python
"""
tests/test_router_telnet_integration.py
Live integration helpers that launch the autopot telnet server and issue real commands.
Future tests can reuse the shared utilities in this file to cover additional scenarios.
"""
import asyncio
import re
import sys
import time
from pathlib import Path

import pytest

telnetlib3 = pytest.importorskip("telnetlib3")

PY = sys.executable
SERVER_CMD = [PY, "-u", "-m", "autopot.server", "--port", "0"]
LOGIN_PROMPT = "login: "
PASSWORD_PROMPT = "Password: "


async def start_server_proc():
    print("[test] launching autopot server")
    proc = await asyncio.create_subprocess_exec(
        *SERVER_CMD,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    start = time.time()
    host = None
    port = None
    while True:
        if proc.stdout.at_eof():
            raise RuntimeError("Server exited before listening")
        line = await proc.stdout.readline()
        if not line:
            await asyncio.sleep(0.05)
            if time.time() - start > 5.0:
                break
            continue
        text = line.decode("utf-8", errors="replace").strip()
        match = re.search(r"Listening on ([0-9\.]+):([0-9]+)", text)
        if match:
            host = match.group(1)
            port = int(match.group(2))
            break
        if time.time() - start > 5.0:
            break
    if host is None or port is None:
        err = await proc.stderr.read()
        raise RuntimeError(
            "Failed to start server; stderr=" + err.decode("utf-8", errors="replace")
        )
    print(f"[test] server listening on {host}:{port}")
    return proc, host, port


async def stop_server_proc(proc):
    print("[test] stopping autopot server")
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    print("[test] server process terminated")


async def _read_until(reader, delimiter, timeout=5.0):
    delim_bytes = (
        delimiter
        if isinstance(delimiter, (bytes, bytearray))
        else delimiter.encode("utf-8")
    )
    data = await asyncio.wait_for(reader.readuntil(delim_bytes), timeout=timeout)
    return data.decode("utf-8", errors="replace")


async def _read_command_output(reader, expected_len, *, timeout=5.0):
    target = expected_len + 2
    buffer = ""
    while len(buffer) < target:
        chunk = await asyncio.wait_for(reader.read(1024), timeout=timeout)
        if not chunk:
            break
        buffer += chunk
    return buffer[:expected_len]


def normalize_text(raw: str) -> str:
    """
    Normalize server output to simple newlines so canned files can be compared reliably.
    """
    return raw.replace("\r\n", "\n").rstrip("\n")


class TelnetSession:
    """
    Async helper that keeps a telnet connection open so multiple commands can share the same session.
    """

    def __init__(self, host, port, *, username="pytest", password="pytest"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.reader = None
        self.writer = None
        self.prompt = None

    async def __aenter__(self):
        self.reader, self.writer = await telnetlib3.open_connection(
            host=self.host, port=self.port, encoding="utf-8"
        )
        await self._authenticate()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb):
        await self.close()

    async def _authenticate(self):
        await _read_until(self.reader, LOGIN_PROMPT)
        self.writer.write(f"{self.username}\r\n")
        await self.writer.drain()
        await _read_until(self.reader, PASSWORD_PROMPT)
        self.writer.write(f"{self.password}\r\n")
        await self.writer.drain()
        self.prompt = await _read_until(self.reader, "$ ")

    async def run_command(self, command: str) -> str:
        if self.writer is None:
            raise RuntimeError("Telnet session is not connected")
        self.writer.write(f"{command}\r\n")
        await self.writer.drain()
        delimiter = self.prompt or "$ "
        response = await _read_until(self.reader, delimiter)
        if delimiter and response.endswith(delimiter):
            response = response[: -len(delimiter)]
        return normalize_text(response)

    async def close(self):
        if self.writer is None:
            return
        self.writer.close()
        await self.writer.wait_closed()
        self.reader = None
        self.writer = None


async def run_telnet_command(
    host,
    port,
    command,
    *,
    expected_response,
    username="pytest",
    password="pytest",
):
    print(f"[test] connecting to {host}:{port}")
    reader, writer = await telnetlib3.open_connection(
        host=host, port=port, encoding="utf-8"
    )
    try:
        print(f"[test] authenticating as {username}")
        await _read_until(reader, LOGIN_PROMPT)
        writer.write(f"{username}\r\n")
        await writer.drain()
        await _read_until(reader, PASSWORD_PROMPT)
        writer.write(f"{password}\r\n")
        await writer.drain()
        await _read_until(reader, "$ ")
        print(f"[test] issuing command '{command}'")
        writer.write(f"{command}\r\n")
        await writer.drain()
        print("[test] awaiting command output")
        response = await _read_command_output(reader, len(expected_response))
        print(
            f"[test] received {len(response)} chars from server (expected {len(expected_response)})"
        )
        return normalize_text(response)
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_server_dispatches_default_passwd():
    proc, host, port = await start_server_proc()
    expected = Path("scenarios/default/txtcmds/etc_passwd.txt").read_text(
        encoding="utf-8"
    )
    try:
        actual = await run_telnet_command(
            host, port, "cat /etc/passwd", expected_response=expected
        )
        print("[test] validating command output:", actual)
    finally:
        await stop_server_proc(proc)

    assert actual == normalize_text(expected)


@pytest.mark.asyncio
async def test_server_dispatches_default_uname():
    proc, host, port = await start_server_proc()
    expected = Path("scenarios/default/txtcmds/uname.txt").read_text(encoding="utf-8")
    try:
        actual = await run_telnet_command(
            host, port, "uname -a", expected_response=expected
        )
        print("[test] validating command output:", actual)
    finally:
        await stop_server_proc(proc)

    assert actual == normalize_text(expected)


@pytest.mark.asyncio
async def test_server_dispatches_default_id():
    proc, host, port = await start_server_proc()
    username = "pytest"
    expected = f"uid=1000({username}) gid=1000({username}) groups=1000({username})"
    try:
        actual = await run_telnet_command(
            host,
            port,
            "id",
            expected_response=expected,
            username=username,
        )
        print("[test] validating command output:", actual)
    finally:
        await stop_server_proc(proc)

    assert actual == normalize_text(expected)


@pytest.mark.asyncio
async def test_server_dispatches_default_whoami():
    proc, host, port = await start_server_proc()
    username = "pytest"
    expected = username
    try:
        actual = await run_telnet_command(
            host,
            port,
            "whoami",
            expected_response=expected,
            username=username,
        )
        print("[test] validating command output:", actual)
    finally:
        await stop_server_proc(proc)

    assert actual == normalize_text(expected)


@pytest.mark.asyncio
async def test_server_dispatches_id_and_whoami_same_session():
    proc, host, port = await start_server_proc()
    username = "pytest"
    expected_id = f"uid=1000({username}) gid=1000({username}) groups=1000({username})"
    id_result = ""
    whoami_result = ""
    try:
        async with TelnetSession(host, port, username=username) as session:
            id_result = await session.run_command("id")
            print("[test] validating id output on shared session:", id_result)
            whoami_result = await session.run_command("whoami")
            print("[test] validating whoami output on shared session:", whoami_result)
    finally:
        await stop_server_proc(proc)

    assert id_result == normalize_text(expected_id)
    assert whoami_result == normalize_text(username)
