# python
"""
autopot/server.py
Asyncio telnet server using telnetlib3
"""
import asyncio
import datetime
import uuid
import pathlib
from typing import Optional
import telnetlib3
import binascii
import logging
from .session import Session
from .auth import AuthGate
from .router import Router

DEFAULT_CONFIG = {
    "server": {
        "host": "0.0.0.0",
        "port": 2323,
        "banner": "Welcome to mini-telnetd"
    },
    "paths": {
        "logs_dir": "logs",
        "tty_dir": "logs/tty",
        "events_file": "logs/events.jsonl",
        "txtcmds_dir": "txtcmds",
        "userdb": "etc/userdb.txt"
    },
    "auth": {
        "max_attempts": 3,
        "fail_delay_seconds": 2
    },
    "limits": {
        "max_output_bytes": 16384,
        "max_line_length": 4096
    },
    "version": "0.1"
}

CONFIG = DEFAULT_CONFIG

def _ensure_dirs():
    pathlib.Path(CONFIG["paths"]["logs_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["tty_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["txtcmds_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["userdb"]).parent.mkdir(parents=True, exist_ok=True)

async def shell(reader, writer) -> None:
    peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
    session_id = str(uuid.uuid4())
    tty_path = str(pathlib.Path(CONFIG["paths"]["tty_dir"]) / f"{session_id}.log")
    session = Session(
        session_id=session_id,
        remote_ip=peer[0],
        remote_port=peer[1],
        # use timezone-aware UTC ISO timestamps to avoid naive/aware datetime arithmetic
        started_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        username=None,
        tty_path=tty_path,
        bytes_in=0,
        bytes_out=0,
        _events_file=CONFIG["paths"]["events_file"],
    )
    await session.log("session.connect", "connect", banner=CONFIG["server"]["banner"])
    await session.write_tty("out", CONFIG["server"]["banner"])
    try:
        writer.write(CONFIG["server"]["banner"] + "\r\n")
        await writer.drain()

        # record that we're about to enter auth; helps diagnose immediate closes
        await session.log("auth.start", "auth")

        # allow more time for telnet option negotiation frames to settle
        # (some clients send multiple SB sequences immediately after connect)
        try:
            await asyncio.sleep(1.0)
        except Exception:
            pass

        auth = AuthGate(session, pathlib.Path(CONFIG["paths"]["userdb"]),
                        max_attempts=CONFIG["auth"]["max_attempts"],
                        fail_delay=CONFIG["auth"]["fail_delay_seconds"])
        ok = await auth.run(reader, writer)
        if not ok:
            await session.log("session.close", "close", duration_ms=0,
                              tty_path=session.tty_path,
                              bytes_in=session.bytes_in, bytes_out=session.bytes_out)
            return
        router = Router(pathlib.Path(CONFIG["paths"]["txtcmds_dir"]),
                        max_output=CONFIG["limits"]["max_output_bytes"])
        prompt = lambda: f"{session.username or 'guest'}@honeypot$ "
        while True:
            writer.write(prompt())
            await writer.drain()
            line = await reader.readline()
            if line is None:
                break
            line = line.rstrip("\r\n")
            if not line:
                continue
            await session.write_tty("in", line)
            await session.log("command.input", "shell", raw=line, argv=line.split())
            out, truncated = await router.dispatch(session, line)
            await session.write_tty("out", out)
            await session.log("command.output", "shell", bytes=len(out.encode()), truncated=truncated)
            writer.write(out + "\r\n")
            await writer.drain()
    except Exception:
        # avoid surfacing exceptions to clients; ensure we still close cleanly
        pass
    finally:
        # compute duration using timezone-aware datetimes
        started = datetime.datetime.fromisoformat(session.started_ts)
        now = datetime.datetime.now(datetime.timezone.utc)
        duration_ms = int((now - started).total_seconds() * 1000)
        await session.log("session.close", "close", duration_ms=duration_ms,
                          tty_path=session.tty_path,
                          bytes_in=session.bytes_in, bytes_out=session.bytes_out)
        await session.finalize_close()
        try:
            writer.close()
        except Exception:
            pass

async def start_server(config: Optional[dict] = None):
    global CONFIG
    if config:
        # shallow merge; caller may pass full config
        CONFIG = {**DEFAULT_CONFIG, **config}
    _ensure_dirs()
    host = CONFIG["server"]["host"]
    port = CONFIG["server"]["port"]
    # Create the telnet server. telnetlib3.create_server returns an asyncio.Server-like
    # object; keep the process alive by waiting on an Event until interrupted.
    server = await telnetlib3.create_server(shell=shell, host=host, port=port)
    print(f"Listening on {host}:{port}")
    try:
        # block forever until cancelled (e.g., Ctrl+C)
        await asyncio.Event().wait()
    finally:
        try:
            server.close()
            await server.wait_closed()
        except Exception:
            pass
    return server

if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_CONFIG["server"]["port"])
    args = parser.parse_args()
    DEFAULT_CONFIG["server"]["port"] = args.port
    asyncio.run(start_server(DEFAULT_CONFIG))