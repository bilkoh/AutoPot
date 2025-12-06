# python
"""
autopot/router.py
Simple command router that dispatches to handlers or returns canned txtcmds.
"""
import shlex
import pathlib
import asyncio
from typing import Tuple, List, Optional
from .session import Session
from .scenario import ScenarioManager

TXT_CMD_MAP = {
    "pwd": "pwd.txt",
    "ls": "ls.txt",
    "df": "df.txt",
    "ps": "ps.txt",
    "busybox": "busybox.txt",
    # uname is handled by a real handler for `uname -a`
    # cat /etc/passwd -> etc_passwd.txt
}


class Router:
    def __init__(
        self,
        txtcmds_dir: Optional[pathlib.Path] = None,
        scenarios_root: Optional[pathlib.Path] = None,
        max_output: int = 16_384,
    ):
        # Keep txtcmds_dir param for backward compatibility but prefer scenario assets.
        self.txtcmds_dir = pathlib.Path(txtcmds_dir) if txtcmds_dir else None
        self.scenario_mgr = ScenarioManager(scenarios_root)
        self.max_output = int(max_output)

    async def dispatch(self, session: Session, line: str) -> Tuple[str, bool]:
        """
        Dispatch a single input line and return (output, truncated_flag).
        Do NOT execute any subprocesses. All outputs are from handlers or
        static files under txtcmds_dir.
        """
        line = (line or "").strip()

        if not line:
            return ("", False)

        try:
            argv: List[str] = shlex.split(line)
        except Exception:
            # fallback naive split if shlex fails
            argv = line.split()

        cmd = argv[0] if argv else ""
        if cmd == "id":
            try:
                from .handlers.id import run as id_run

                out = await id_run(session, argv)
            except Exception:
                out = "uid=0(root) gid=0(root) groups=0(root)"
            truncated = len(out.encode()) > self.max_output
            return (out[: self.max_output], truncated)
        if cmd == "whoami":
            try:
                from .handlers.whoami import run as whoami_run

                out = await whoami_run(session, argv)
            except Exception:
                out = session.username or "guest"
            truncated = len(out.encode()) > self.max_output
            return (out[: self.max_output], truncated)
        # Special-case: uname -a -> handler
        # if cmd == "uname":
        #     # delegate to handler which returns a plausible string
        #     try:
        #         from .handlers.uname import run as uname_run
        #         out = await uname_run(session, argv)
        #     except Exception:
        #         out = "Linux unknown 0.0.0 unknown x86_64"
        #     truncated = len(out.encode()) > self.max_output
        #     return (out[: self.max_output], truncated)

        # Special-case: cat /etc/passwd
        if cmd == "cat" and len(argv) >= 2 and argv[1] in ("/etc/passwd", "etc/passwd"):
            # prefer scenario-specific etc_passwd.txt (includes scenarios/default)
            p = None
            try:
                p = self.scenario_mgr.get_txtcmd_path(session, "etc_passwd")
            except Exception:
                p = None
            if p:
                return await self._read_txt_file(p)
            # no legacy top-level fallback anymore: return empty result
            return ("", False)

        # Special-case: cat /etc/shadow
        if cmd == "cat" and len(argv) >= 2 and argv[1] in ("/etc/shadow", "etc/shadow"):
            # prefer scenario-specific etc_shadow.txt (includes scenarios/default)
            p = None
            try:
                p = self.scenario_mgr.get_txtcmd_path(session, "etc_shadow")
            except Exception:
                p = None
            if p:
                return await self._read_txt_file(p)
            # no legacy top-level fallback anymore: return empty result
            return ("", False)

        # static mapping (with scenario overrides)
        if cmd in TXT_CMD_MAP:
            mapped = TXT_CMD_MAP[cmd]
            name = mapped.rsplit(".", 1)[0]
            p = None
            try:
                p = self.scenario_mgr.get_txtcmd_path(session, name)
            except Exception:
                p = None
            if p:
                return await self._read_txt_file(p)
            # no legacy top-level fallback anymore: command not found
            return (f"sh: {cmd}: command not found", False)

        # try scenario-specific txtcmd for command
        p = None
        try:
            p = self.scenario_mgr.get_txtcmd_path(session, cmd)
        except Exception:
            p = None
        if p:
            return await self._read_txt_file(p)

        # try scenario-specific txtcmd for command was checked earlier.
        # No legacy top-level txtcmds fallback: return command not found.
        return (f"sh: {cmd}: command not found", False)

    async def _read_txt_file(self, path: pathlib.Path) -> Tuple[str, bool]:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ("", False)
        except Exception:
            return ("", False)
        truncated = len(text.encode()) > self.max_output
        return (text[: self.max_output], truncated)
