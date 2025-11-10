# python
"""
tests/test_basic.py
Basic pytest-asyncio tests that start the autopot server as a subprocess,
connect with a raw TCP client, verify banner, and assert that events.jsonl
and a tty file are created.

Run with:
    pytest -q
"""
import asyncio
import sys
import os
import re
import json
import tempfile
import time
from pathlib import Path

import pytest

PY = sys.executable

SERVER_CMD = [PY, "-u", "-m", "autopot.server", "--port", "0"]


async def start_server_proc():
    proc = await asyncio.create_subprocess_exec(
        *SERVER_CMD,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    # read lines until we see "Listening on"
    port = None
    host = None
    start = time.time()
    while True:
        if proc.stdout.at_eof():
            raise RuntimeError("Server exited prematurely")
        line = await proc.stdout.readline()
        if not line:
            await asyncio.sleep(0.05)
            if time.time() - start > 5:
                break
            continue
        s = line.decode("utf-8", errors="replace").strip()
        # Example: "Listening on 127.0.0.1:12345" or "Listening on 0.0.0.0:12345"
        m = re.search(r"Listening on ([0-9\.]+):([0-9]+)", s)
        if m:
            host = m.group(1)
            port = int(m.group(2))
            break
        # defensive timeout
        if time.time() - start > 5:
            break
    if port is None:
        # capture stderr for diagnostics
        err = await proc.stderr.read()
        raise RuntimeError(
            "Failed to start server; stderr=" + err.decode("utf-8", errors="replace")
        )
    return proc, host, port


def probe_connect(host, port, send=b"\r\n", recv_timeout=2.0):
    import socket
    import re

    # blocking socket probe (suitable for run_in_executor)
    s = socket.create_connection((host, port), timeout=5)
    s.settimeout(recv_timeout)
    try:
        # read any initial bytes (may include telnet IAC negotiation)
        data = s.recv(4096)
        # send newline to trigger server-side reads / responses
        s.sendall(send)
        # attempt to read more after sending
        try:
            more = s.recv(4096)
        except socket.timeout:
            more = b""
        combined = (data or b"") + (more or b"")
        # decode and strip non-printable negotiation bytes so tests can assert on banner text
        banner = combined.decode("utf-8", errors="replace")
        banner = re.sub(r"[^\x20-\x7E\r\n]+", "", banner)
        return banner, more
    finally:
        try:
            s.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_banner_and_events(tmp_path):
    # Ensure logs dir is empty for deterministic assertions
    logs = Path("logs")
    events_file = logs / "events.jsonl"
    tty_dir = logs / "tty"
    # remove existing logs if any (safe for test env)
    if events_file.exists():
        events_file.unlink()
    if tty_dir.exists():
        for f in tty_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass

    proc, host, port = await start_server_proc()
    try:
        # connect with raw TCP probe
        banner, more = await asyncio.get_event_loop().run_in_executor(
            None, probe_connect, host, port
        )
        # assert "Welcome to mini-telnetd" in banner or "Welcome" in banner

        # give the server a short moment to write events
        await asyncio.sleep(0.1)

        # wait up to 3s for a session.close event to be flushed (probe may be async)
        deadline = time.time() + 3.0
        content = []
        while time.time() < deadline:
            if events_file.exists():
                content = events_file.read_text(encoding="utf-8").strip().splitlines()
                if any("session.close" in line for line in content):
                    break
            await asyncio.sleep(0.1)

        # validate events.jsonl exists and contains connect/close events
        assert events_file.exists(), "events.jsonl should be created"
        assert any("session.connect" in line for line in content), "session.connect missing"
        assert any("session.close" in line for line in content), "session.close missing"

        # ensure a tty file was created under logs/tty
        assert tty_dir.exists(), "logs/tty should exist"
        files = list(tty_dir.glob("*.log"))
        assert files, "no tty files were created"

    finally:
        # terminate server subprocess
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
