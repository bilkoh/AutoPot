from pathlib import Path
from typing import Optional, Dict, Any
import json


class ScenarioManager:
    """
    Locate scenario-specific assets under a scenarios root.

    Layout:
      scenarios/{scenario_id}/txtcmds/{cmd}.txt
      scenarios/{scenario_id}/fs.json

    Public API:
      get_txtcmd_path(session, cmdname) -> Path | None
      load_fs(session) -> Dict | None
    """

    def __init__(self, scenarios_root: Optional[Path] = None):
        self.scenarios_root = Path(scenarios_root or Path("scenarios")).resolve()

    def _scenario_dir(self, scenario_id: str) -> Path:
        return self.scenarios_root / scenario_id

    def get_txtcmd_path(self, session: Any, cmdname: str) -> Optional[Path]:
        """
        Return the first matching txtcmd Path for the session's scenario,
        falling back to the 'default' scenario. Returns None if not found.
        """
        if not cmdname:
            return None
        # candidate paths in order
        candidates = []
        if getattr(session, "scenario_id", None):
            candidates.append(self._scenario_dir(session.scenario_id) / "txtcmds" / f"{cmdname}.txt")
        candidates.append(self._scenario_dir("default") / "txtcmds" / f"{cmdname}.txt")

        for p in candidates:
            try:
                if p.exists():
                    return p
            except Exception:
                # be conservative: ignore filesystem errors and continue
                continue
        return None

    def load_fs(self, session: Any) -> Optional[Dict[str, Any]]:
        """
        Load scenarios/{scenario_id}/fs.json if present, otherwise
        scenarios/default/fs.json. Returns parsed JSON dict or None.
        """
        candidates = []
        if getattr(session, "scenario_id", None):
            candidates.append(self._scenario_dir(session.scenario_id) / "fs.json")
        candidates.append(self._scenario_dir("default") / "fs.json")

        for p in candidates:
            try:
                if p.exists():
                    text = p.read_text(encoding="utf-8")
                    return json.loads(text)
            except Exception:
                # ignore JSON/IO errors and try next candidate
                continue
        return None