# python
"""
autopot/router.py
Simple command router that dispatches to handlers or returns canned txtcmds.
"""
import logging
import shlex
import pathlib
import asyncio
from typing import Tuple, List, Optional, Dict, Any
from .session import Session
from .scenario import ScenarioManager
from .fs_snapshot import (
    FileSystemSnapshot,
    BASE_FS_PATH_PARTS,
    ROOT_FS_PATH,
)
from .llm import LLMClient

logger = logging.getLogger(__name__)

TXT_CMD_MAP = {
    "pwd": "pwd.txt",
    "ls": "ls.txt",
    "df": "df.txt",
    "ps": "ps.txt",
    "busybox": "busybox.txt",
    # uname is handled by a real handler for `uname -a`
    # cat /etc/passwd -> etc_passwd.txt
}


DEFAULT_DIR_PERMS = "drwxr-xr-x"
DEFAULT_FILE_PERMS = "-rw-r--r--"
DEFAULT_OWNER = "user"
DEFAULT_GROUP = "user"
DEFAULT_TIMESTAMP = "Jan 01 00:00"


def _format_ls_entry(node: dict, name: str) -> str:
    perms = DEFAULT_DIR_PERMS if node.get("type") == "dir" else DEFAULT_FILE_PERMS
    links = 2 if node.get("type") == "dir" else 1
    size = node.get("size", 0) or 0
    return f"{perms} {links:>3} {DEFAULT_OWNER} {DEFAULT_GROUP} {size:>8} {DEFAULT_TIMESTAMP} {name}"


class Router:
    def __init__(
        self,
        txtcmds_dir: Optional[pathlib.Path] = None,
        scenarios_root: Optional[pathlib.Path] = None,
        max_output: int = 16_384,
        llm_client: Optional[LLMClient] = None,
    ):
        # Keep txtcmds_dir param for backward compatibility but prefer scenario assets.
        self.txtcmds_dir = pathlib.Path(txtcmds_dir) if txtcmds_dir else None
        self.scenario_mgr = ScenarioManager(scenarios_root)
        self.max_output = int(max_output)
        self.llm_client = llm_client

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
        if cmd == "history":
            try:
                from .handlers.history import run as history_run

                out = await history_run(session, argv)
            except Exception:
                out = "\n".join(session.history)
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

        builtin = self._handle_builtin(session, argv)
        if builtin is not None:
            out, _ = builtin
            truncated = len(out.encode()) > self.max_output
            return (out[: self.max_output], truncated)

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

        if self.llm_client:
            return await self._simulate_with_llm(session, line, cmd)

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

    async def _simulate_with_llm(
        self, session: Session, line: str, cmd: str
    ) -> Tuple[str, bool]:
        fs = self._get_fs_for_simulation(session)
        history = list(session.history)

        try:
            response = await asyncio.to_thread(
                self.llm_client.simulate_command, line, fs, history
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LLM simulate_command failed for %s", cmd)
            await session.log(
                "llm.simulate_command",
                "llm",
                command=line,
                error="simulate_command raised an exception",
            )
            return (f"sh: {cmd}: command not found", False)
        
        if not isinstance(response, dict):
            logger.warning("LLM simulate_command returned unexpected response for %s", cmd)
            await session.log(
                "llm.simulate_command",
                "llm",
                command=line,
                raw_response=str(response),
            )
            return (f"sh: {cmd}: command not found", False)
        
        output = self._format_simulated_output(response)
        truncated = len(output.encode()) > self.max_output
        await session.log(
            "llm.simulate_command",
            "llm",
            command=line,
            response=response,
            output=output,
            truncated=truncated,
        )
        return (output[: self.max_output], truncated)

    def _format_simulated_output(self, response: Dict[str, Any]) -> str:
        stdout = response.get("stdout", "")
        stderr = response.get("stderr", "")
        if stdout and stderr:
            return "\n".join([stdout, stderr])
        return stdout or stderr or ""

    def _handle_builtin(self, session: Session, argv: List[str]) -> Optional[Tuple[str, bool]]:
        if not argv:
            return None
        cmd = argv[0]
        if cmd == "pwd":
            return (session.cwd, False)
        if cmd == "cd":
            return self._handle_cd(session, argv)
        if cmd == "ls":
            return self._handle_ls(session, argv)
        return None

    def _handle_cd(self, session: Session, argv: List[str]) -> Optional[Tuple[str, bool]]:
        dest = argv[1] if len(argv) > 1 else ROOT_FS_PATH
        snapshot = self._get_fs_snapshot(session)
        if not snapshot:
            return None
        parts = self._resolve_target_parts(session, dest)
        if parts is None:
            display = argv[1] if len(argv) > 1 else dest
            return (f"bash: cd: {display}: No such file or directory", False)
        rel = tuple(parts[len(BASE_FS_PATH_PARTS) :])
        node = snapshot.get_node(rel)
        if not node or node.get("type") != "dir":
            display = argv[1] if len(argv) > 1 else dest
            return (f"bash: cd: {display}: No such file or directory", False)
        session.cwd = "/" + "/".join(parts)
        return ("", False)

    def _handle_ls(self, session: Session, argv: List[str]) -> Optional[Tuple[str, bool]]:
        snapshot = self._get_fs_snapshot(session)
        if not snapshot:
            return None
        args = [arg for arg in argv[1:] if arg and not arg.startswith("-")]
        target = args[0] if args else ""
        parts = self._resolve_target_parts(session, target)
        if parts is None:
            display = target or "."
            return (f"ls: cannot access '{display}': No such file or directory", False)
        rel = tuple(parts[len(BASE_FS_PATH_PARTS) :])
        node = snapshot.get_node(rel)
        if not node:
            display = target or "."
            return (f"ls: cannot access '{display}': No such file or directory", False)
        if node.get("type") != "dir":
            display_name = node.get("name") or target or ""
            return (_format_ls_entry(node, display_name), False)

        children = snapshot.list_dir(rel) or []
        lines: List[str] = []
        lines.append(_format_ls_entry(node, "."))
        parent_rel = rel[:-1] if rel else rel
        parent_node = snapshot.get_node(parent_rel) or node
        lines.append(_format_ls_entry(parent_node, ".."))
        sorted_children = sorted(children, key=lambda entry: entry.get("name") or "")
        for child in sorted_children:
            name = child.get("name") or ""
            lines.append(_format_ls_entry(child, name))
        return ("\n".join(lines), False)

    def _get_fs_snapshot(self, session: Session) -> Optional[FileSystemSnapshot]:
        if session.scenario_fs_snapshot:
            return session.scenario_fs_snapshot
        raw = session.scenario_fs or self.scenario_mgr.load_fs(session)
        if not raw:
            return None
        snapshot = FileSystemSnapshot(raw)
        session.scenario_fs = raw
        session.scenario_fs_snapshot = snapshot
        return snapshot

    def _get_fs_for_simulation(self, session: Session) -> Dict[str, Any]:
        fs = session.scenario_fs
        if not fs:
            raw = self.scenario_mgr.load_fs(session)
            if raw:
                fs = raw
            else:
                fs = {"type": "dir", "name": BASE_FS_PATH_PARTS[-1], "children": []}
            session.scenario_fs = fs
        return fs

    def _resolve_target_parts(self, session: Session, target: str) -> Optional[List[str]]:
        target = (target or "").strip()
        if target.startswith("/"):
            parts: List[str] = []
            for entry in target.split("/"):
                if not entry or entry == ".":
                    continue
                if entry == "..":
                    if parts:
                        parts.pop()
                    continue
                parts.append(entry)
            if len(parts) < len(BASE_FS_PATH_PARTS):
                return None
            if tuple(parts[: len(BASE_FS_PATH_PARTS)]) != BASE_FS_PATH_PARTS:
                return None
            return parts

        cwd_parts = [pt for pt in session.cwd.strip("/").split("/") if pt]
        if len(cwd_parts) < len(BASE_FS_PATH_PARTS) or tuple(
            cwd_parts[: len(BASE_FS_PATH_PARTS)]
        ) != BASE_FS_PATH_PARTS:
            cwd_parts = list(BASE_FS_PATH_PARTS)
        for entry in target.split("/"):
            if not entry or entry == ".":
                continue
            if entry == "..":
                if len(cwd_parts) > len(BASE_FS_PATH_PARTS):
                    cwd_parts.pop()
                continue
            cwd_parts.append(entry)
        return cwd_parts
