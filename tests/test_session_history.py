# python
"""
tests/test_session.py
Unit tests covering the new Session history tracking helpers.
"""
from pathlib import Path

from autopot.session import Session, iso_ts


def _create_session(tmp_path: Path) -> Session:
    tty_path = tmp_path / "tty.log"
    events_file = tmp_path / "events.jsonl"
    return Session(
        session_id="test-session",
        remote_ip="127.0.0.1",
        remote_port=12345,
        started_ts=iso_ts(),
        tty_path=str(tty_path),
        _events_file=str(events_file),
    )


def test_history_starts_empty(tmp_path: Path) -> None:
    session = _create_session(tmp_path)
    assert session.history == []


def test_recording_commands_appends_history(tmp_path: Path) -> None:
    session = _create_session(tmp_path)
    session.record_command("ls -la")
    session.record_command("pwd")
    assert session.history == ["ls -la", "pwd"]


def test_empty_input_is_ignored(tmp_path: Path) -> None:
    session = _create_session(tmp_path)
    session.record_command("")
    session.record_command("date +%s")
    assert session.history == ["date +%s"]


def test_cwd_defaults_to_home(tmp_path: Path) -> None:
    session = _create_session(tmp_path)
    assert session.cwd == "/home/user"
