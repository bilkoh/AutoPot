# python
"""
tests/test_router_llm.py
Unit tests verifying the router delegates unknown commands to an LLM client.
"""
from pathlib import Path
import asyncio
import json

from autopot.router import Router
from autopot.session import Session, iso_ts


class DummyLLMClient:
    def __init__(self):
        self.calls = []

    def simulate_command(self, command, fs, bash_history, *, model=None):
        self.calls.append((command, fs, bash_history))
        return {
            "stdout": f"simulated stdout for {command}",
            "stderr": "simulated stderr",
            "exit_code": 0,
            "explanation": "ok",
        }


class FailingLLMClient:
    def simulate_command(self, *args, **kwargs):
        raise RuntimeError("simulate failed")


def _make_router(llm_client):
    repo_root = Path(__file__).resolve().parents[1]
    return Router(
        scenarios_root=repo_root / "scenarios",
        llm_client=llm_client,
        max_output=16384,
    )


def _make_session(tmp_path: Path) -> Session:
    return Session(
        session_id="test-session",
        remote_ip="127.0.0.1",
        remote_port=12345,
        started_ts=iso_ts(),
        tty_path=str(tmp_path / "tty.log"),
        _events_file=str(tmp_path / "events.jsonl"),
    )


def test_router_delegates_fallback_to_llm(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    client = DummyLLMClient()
    router = _make_router(client)
    session.record_command("ls")
    session.record_command("netstat")

    output, truncated = asyncio.run(router.dispatch(session, "netstat"))

    assert not truncated
    assert output == "simulated stdout for netstat\nsimulated stderr"
    assert len(client.calls) == 1
    called_cmd, fs, history = client.calls[0]
    assert called_cmd == "netstat"
    assert history == ["ls", "netstat"]
    assert fs.get("type") == "dir"
    assert fs.get("name") == "user"
    events = list((tmp_path / "events.jsonl").read_text().splitlines())
    assert len(events) == 1
    log_entry = json.loads(events[0])
    assert log_entry["event"] == "llm.simulate_command"
    payload = log_entry["payload"]
    assert payload["command"] == "netstat"
    assert payload["response"]["stdout"] == "simulated stdout for netstat"
    assert payload["response"]["stderr"] == "simulated stderr"
    assert payload["output"] == "simulated stdout for netstat\nsimulated stderr"
    assert payload["truncated"] is False


def test_router_falls_back_when_llm_errors(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    client = FailingLLMClient()
    router = _make_router(client)
    session.record_command("broken")

    output, truncated = asyncio.run(router.dispatch(session, "broken"))

    assert not truncated
    assert output == "sh: broken: command not found"
