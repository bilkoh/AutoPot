# python
"""
autopot/server.py
Asyncio telnet server using telnetlib3
"""
import asyncio
import datetime
import uuid
import pathlib
import os
from typing import Optional
import telnetlib3
from telnetlib3.telopt import ECHO, WILL
import binascii
import logging
from .session import Session
from .auth import AuthGate
from .router import Router
from .env import load_env
from .llm import create_llm_client, LLMClient

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 2323, "banner": "Welcome to mini-telnetd"},
    "paths": {
        "logs_dir": "logs",
        "tty_dir": "logs/tty",
        "events_file": "logs/events.jsonl",
        "txtcmds_dir": "txtcmds",
        "userdb": "etc/userdb.txt",
    },
    "auth": {"max_attempts": 3, "fail_delay_seconds": 2},
    "limits": {"max_output_bytes": 16384, "max_line_length": 4096},
    "version": "0.1",
    "hostname": "autopot",
}

CONFIG = DEFAULT_CONFIG


def _ensure_dirs():
    pathlib.Path(CONFIG["paths"]["logs_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["tty_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["txtcmds_dir"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(CONFIG["paths"]["userdb"]).parent.mkdir(parents=True, exist_ok=True)


def _normalize_for_terminal(text: str) -> str:
    """
    Convert newline usage to CRLF sequences that telnet clients expect.
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "\r\n")


def _create_configured_llm_client() -> Optional[LLMClient]:
    load_env()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL")
    if openai_api_key and openai_model:
        try:
            client = create_llm_client(
                "openai-compat",
                base_url=os.getenv("OPENAI_BASE_URL"),
                api_key=openai_api_key,
                model=openai_model,
            )
            logger.info("Using OpenAI-compatible LLM model %s for command fallback", openai_model)
            return client
        except Exception as exc:
            logger.warning("Failed to initialize OpenAI LLM client: %s", exc)
    
    gemini_model = os.getenv("GEMINI_MODEL")
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_model and gemini_api_key:
        try:
            client = create_llm_client("gemini", api_key=gemini_api_key, model=gemini_model)
            logger.info("Using Gemini LLM model %s for command fallback", gemini_model)
            return client
        except Exception as exc:
            logger.warning("Failed to initialize Gemini LLM client: %s", exc)
    logger.debug("No LLM provider configured for command fallback")
    return None


LLM_CLIENT = _create_configured_llm_client()


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
    try:
        if hasattr(writer, "iac"):
            writer.iac(WILL, ECHO)
    except Exception:  # pragma: no cover
        pass
    await session.log("session.connect", "connect", banner=CONFIG["server"]["banner"])
    await session.write_tty("out", CONFIG["server"]["banner"])
    try:
        # allow a short window for clients to send initial telnet negotiation
        # frames so the banner doesn't get interleaved with IAC bytes when probed
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # send the textual banner after negotiation has settled
        writer.write(CONFIG["server"]["banner"] + "\r\n")
        await writer.drain()

        # record that we're about to enter auth; helps diagnose immediate closes
        await session.log("auth.start", "auth")

        # keep a small extra delay to be defensive for aggressive clients
        try:
            await asyncio.sleep(0.1)
        except Exception:
            pass

        auth = AuthGate(
            session,
            pathlib.Path(CONFIG["paths"]["userdb"]),
            max_attempts=CONFIG["auth"]["max_attempts"],
            fail_delay=CONFIG["auth"]["fail_delay_seconds"],
        )
        ok = await auth.run(reader, writer)
        if not ok:
            await session.log(
                "session.close",
                "close",
                duration_ms=0,
                tty_path=session.tty_path,
                bytes_in=session.bytes_in,
                bytes_out=session.bytes_out,
            )
            return

        router = Router(
            pathlib.Path(CONFIG["paths"]["txtcmds_dir"]),
            max_output=CONFIG["limits"]["max_output_bytes"],
            llm_client=LLM_CLIENT,
        )

        prompt = lambda: f"{session.username or 'guest'}@{CONFIG['hostname']}$ "

        while True:
            writer.write(prompt())
            await writer.drain()
            line = await reader.readline()
            if line is None:
                break
            line = line.rstrip("\r\n")
            if not line:
                continue
            session.record_command(line)
            await session.write_tty("in", line)
            argv = line.split()
            await session.log("command.input", "shell", raw=line, argv=argv)
            auto_echo = getattr(writer, "will_echo", False)
            if not auto_echo:
                normalized_input = _normalize_for_terminal(line)
                try:
                    writer.echo(normalized_input + "\r\n")
                except Exception:
                    writer.write(normalized_input + "\r\n")
            cmd = argv[0] if argv else ""
            exit_cmd = cmd in ("exit", "logout")
            if exit_cmd:
                out = ""
                truncated = False
            else:
                out, truncated = await router.dispatch(session, line)
            await session.write_tty("out", out)
            await session.log(
                "command.output", "shell", bytes=len(out.encode()), truncated=truncated
            )
            normalized = _normalize_for_terminal(out)
            if normalized:
                writer.write("\r\n")
            writer.write(normalized + "\r\n")
            await writer.drain()
            if exit_cmd:
                break
    except Exception:
        # avoid surfacing exceptions to clients; ensure we still close cleanly
        pass
    finally:
        # compute duration using timezone-aware datetimes
        started = datetime.datetime.fromisoformat(session.started_ts)
        now = datetime.datetime.now(datetime.timezone.utc)
        duration_ms = int((now - started).total_seconds() * 1000)
        await session.log(
            "session.close",
            "close",
            duration_ms=duration_ms,
            tty_path=session.tty_path,
            bytes_in=session.bytes_in,
            bytes_out=session.bytes_out,
        )
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
    # Create the telnet server. telnetlib3.create_server returns an asyncio.Server-like object.
    server = await telnetlib3.create_server(shell=shell, host=host, port=port)

    # Derive the actual bound address/port from the server sockets so callers
    # (and tests) can connect when port=0 (ephemeral).
    actual_host = host
    actual_port = port
    try:
        socks = getattr(server, "sockets", None)
        if socks:
            sockname = socks[0].getsockname()
            # sockname can be (host, port) or (host, port, flowinfo, scopeid)
            actual_host = sockname[0]
            actual_port = sockname[1]
            # If the socket bound to 0.0.0.0 (all interfaces), prefer localhost
            # for test clients that connect to the server on the same host.
            if actual_host in ("0.0.0.0", "", None, "::"):
                actual_host = "127.0.0.1"
    except Exception:
        # best-effort only; fall back to configured values
        pass

    print(f"Listening on {actual_host}:{actual_port}")
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
