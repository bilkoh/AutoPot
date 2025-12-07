# python
"""
tests/test_router_fs.py
Unit tests for the custom ls/cd/pwd builtin handling backed by scenarios/fs.json.
"""
from pathlib import Path
import asyncio

from autopot.router import Router
from autopot.session import Session, iso_ts


def _entry_names(output: str):
    return {line.split()[-1] for line in output.splitlines() if line.strip()}


def _make_session(tmp_path: Path) -> Session:
    return Session(
        session_id="test-session",
        remote_ip="127.0.0.1",
        remote_port=12345,
        started_ts=iso_ts(),
        tty_path=str(tmp_path / "tty.log"),
    )


def _make_router() -> Router:
    repo_root = Path(__file__).resolve().parents[1]
    return Router(scenarios_root=repo_root / "scenarios")


def _dispatch(router: Router, session: Session, cmd: str):
    return asyncio.run(router.dispatch(session, cmd))


def test_pwd_returns_home(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    output, truncated = _dispatch(router, session, "pwd")
    assert not truncated
    assert output == "/home/user"


def test_ls_shows_directory_entries(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    output, truncated = _dispatch(router, session, "ls")
    assert not truncated
    lines = output.splitlines()
    assert lines, "ls should emit at least the . and .. entries"
    assert lines[0].split()[-1] == "."
    assert lines[1].split()[-1] == ".."
    entry_names = {line.split()[-1] for line in lines}
    assert "bin" in entry_names
    assert "README.txt" in entry_names


def test_cd_changes_cwd(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    out, truncated = _dispatch(router, session, "cd logs")
    assert out == ""
    assert not truncated
    assert session.cwd == "/home/user/logs"
    out, truncated = _dispatch(router, session, "pwd")
    assert out == "/home/user/logs"
    assert not truncated
    _dispatch(router, session, "cd ..")
    assert session.cwd == "/home/user"


def test_ls_with_path_argument(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    output, truncated = _dispatch(router, session, "ls /home/user/config")
    assert not truncated
    names = {line.split()[-1] for line in output.splitlines()}
    assert "camera.conf" in names


def test_ls_flags_are_ignored(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    plain, _ = _dispatch(router, session, "ls")
    flagged, _ = _dispatch(router, session, "ls -la")
    assert plain == flagged
    assert "." in _entry_names(flagged)


def test_ls_flag_with_path(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    flagged, _ = _dispatch(router, session, "ls -la /home/user/logs")
    direct, _ = _dispatch(router, session, "ls /home/user/logs")
    assert flagged == direct
    assert "system.log" in _entry_names(flagged)


def test_cd_dot_segments(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    _dispatch(router, session, "cd ./logs")
    assert session.cwd == "/home/user/logs"
    _dispatch(router, session, "cd ../../bin")
    assert session.cwd == "/home/user/bin"


def test_cd_parent_stays_root(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    out, _ = _dispatch(router, session, "cd ..")
    assert out == ""
    assert session.cwd == "/home/user"
    out, _ = _dispatch(router, session, "cd ..")
    assert out == ""
    assert session.cwd == "/home/user"


def test_ls_file_target(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    output, _ = _dispatch(router, session, "ls README.txt")
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].split()[-1] == "README.txt"


def test_ls_relative_parent_with_dots(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    _dispatch(router, session, "cd bin")
    base_cwd = session.cwd
    output, _ = _dispatch(router, session, "ls ../logs")
    assert session.cwd == base_cwd
    names = _entry_names(output)
    assert "system.log" in names
    assert "auth.log" in names


def test_ls_logs_dot_dot(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    router = _make_router()
    output, _ = _dispatch(router, session, "ls logs/./..")
    names = _entry_names(output)
    assert "." in names
    assert ".." in names
    assert "bin" in names
