# python
"""
tests/test_router_txtcmd_default.py
Unit test verifying Router dispatch resolves canned txtcmds from the default scenario.
"""
from pathlib import Path
import asyncio

from autopot.router import Router
from autopot.session import Session, iso_ts


def test_router_uses_default_txtcmd(tmp_path):
    # Router should resolve scenario assets relative to the repo root.
    repo_root = Path(__file__).resolve().parents[1]
    scenarios_root = repo_root / "scenarios"
    router = Router(scenarios_root=scenarios_root)

    session = Session(
        session_id="test-session",
        remote_ip="127.0.0.1",
        remote_port=12345,
        started_ts=iso_ts(),
        tty_path=str(tmp_path / "tty.log"),
    )

    output, truncated = asyncio.run(router.dispatch(session, "cat /etc/passwd"))
    assert not truncated, "Output from the canned file should not be truncated"

    expected = (scenarios_root / "default" / "txtcmds" / "etc_passwd.txt").read_text(
        encoding="utf-8"
    )
    assert output == expected
