# python
"""
tests/test_router_history.py
Unit tests covering the router history command handler.
"""
from pathlib import Path
import asyncio

from autopot.router import Router
from autopot.session import Session, iso_ts


def _make_session(tmp_path: Path) -> Session:
    return Session(
        session_id="test-session",
        remote_ip="127.0.0.1",
        remote_port=12345,
        started_ts=iso_ts(),
        tty_path=str(tmp_path / "tty.log"),
    )


def _dispatch(router: Router, session: Session, cmd: str):
    return asyncio.run(router.dispatch(session, cmd))


def test_history_returns_recorded_commands(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = Router()
    session.record_command("ls")
    session.record_command("pwd")
    session.record_command("history")

    output, truncated = _dispatch(router, session, "history")
    assert not truncated
    assert output == "ls\npwd\nhistory"


def test_history_handles_empty_session(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = Router()

    output, truncated = _dispatch(router, session, "history")
    assert not truncated
    assert output == ""
