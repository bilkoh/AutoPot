# python
"""
autopot/session.py
Session dataclass and JSONL event logging for the honeypot.
"""
from dataclasses import dataclass, field
import asyncio
import json
import datetime
import pathlib
import uuid
from typing import Optional, Any, Dict, List

_EVENT_LOCK = asyncio.Lock()

def iso_ts():
    """
    Return a timezone-aware UTC ISO timestamp (Z suffix) for logging.
    """
    dt = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")

def ensure_dir(path: pathlib.Path):
    path.mkdir(parents=True, exist_ok=True)

@dataclass
class Session:
    session_id: str
    remote_ip: str
    remote_port: int
    started_ts: str
    username: Optional[str] = None
    scenario_id: str = "default"
    tty_path: str = ""
    bytes_in: int = 0
    bytes_out: int = 0
    _events_file: str = "logs/events.jsonl"
    cwd: str = "/home/user"
    scenario_fs: Optional[Dict[str, Any]] = field(default=None, repr=False)
    scenario_fs_snapshot: Optional[Any] = field(default=None, repr=False)
    history: List[str] = field(default_factory=list, repr=False)
    _tty_lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self):
        tty_path = pathlib.Path(self.tty_path)
        ensure_dir(tty_path.parent)
        self._tty_lock = asyncio.Lock()

    async def log(self, event: str, phase: str, **fields: Any) -> None:
        rec = {
            "ts": iso_ts(),
            "session_id": self.session_id,
            "remote_ip": self.remote_ip,
            "remote_port": self.remote_port,
            "event": event,
            "phase": phase,
            "version": "0.1",
            "payload": fields or {}
        }
        async with _EVENT_LOCK:
            ensure_dir(pathlib.Path(self._events_file).parent)
            with open(self._events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    async def write_tty(self, direction: str, data: str) -> None:
        prefix = "< " if direction == "in" else "> "
        async with self._tty_lock:
            with open(self.tty_path, "a", encoding="utf-8", errors="ignore") as f:
                f.write(f"{prefix}{data}\n")

    def set_scenario(self, scenario_id: str) -> None:
        """
        Set the session's scenario_id and clear any cached scenario filesystem.
        """
        self.scenario_id = scenario_id or "default"
        self.scenario_fs = None
        self.scenario_fs_snapshot = None

    def record_command(self, command: str) -> None:
        """
        Track the raw command line for history/LLM use.
        """
        if command:
            self.history.append(command)

    async def finalize_close(self) -> None:
        # placeholder for any future cleanup hooks
        return
