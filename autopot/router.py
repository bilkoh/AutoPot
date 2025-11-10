# python
"""
autopot/router.py
Simple command router that dispatches to handlers or returns canned txtcmds.
"""
import shlex
import pathlib
import asyncio
from typing import Tuple, List
from .session import Session

TXT_CMD_MAP = {
    "id": "id.txt",
    "pwd": "pwd.txt",
    "ls": "ls.txt",
    "df": "df.txt",
    "ps": "ps.txt",
    "busybox": "busybox.txt",
    # uname is handled by a real handler for `uname -a`
    # cat /etc/passwd -> etc_passwd.txt
}

class Router:
    def __init__(self, txtcmds_dir: pathlib.Path, max_output: int = 16_384):
        self.txtcmds_dir = pathlib.Path(txtcmds_dir)
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
        # Special-case: uname -a -> handler
        if cmd == "uname":
            # delegate to handler which returns a plausible string
            try:
                from .handlers.uname import run as uname_run
                out = await uname_run(session, argv)
            except Exception:
                out = "Linux unknown 0.0.0 unknown x86_64"
            truncated = len(out.encode()) > self.max_output
            return (out[: self.max_output], truncated)
        # Special-case: cat /etc/passwd
        if cmd == "cat" and len(argv) >= 2 and argv[1] in ("/etc/passwd", "etc/passwd"):
            fname = self.txtcmds_dir / "etc_passwd.txt"
            return await self._read_txt_file(fname)
        # static mapping
        if cmd in TXT_CMD_MAP:
            fname = self.txtcmds_dir / TXT_CMD_MAP[cmd]
            return await self._read_txt_file(fname)
        # try exact txtcmd file by command name
        fname = self.txtcmds_dir / f"{cmd}.txt"
        if fname.exists():
            return await self._read_txt_file(fname)
        # fallback: command not found
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