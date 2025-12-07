"""Filesystem snapshot helpers for scenarios/fs.json."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

BASE_FS_PATH_PARTS: Tuple[str, ...] = ("home", "user")
ROOT_FS_PATH = "/" + "/".join(BASE_FS_PATH_PARTS)


class FileSystemSnapshot:
    """
    In-memory representation of a scenario fs.json tree and fast lookups.
    """

    def __init__(self, root: Mapping[str, Any]):
        self.root: Mapping[str, Any] = dict(root)
        self._index: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        self._build_index(self.root, ())

    def _build_index(self, node: Mapping[str, Any], rel_path: Tuple[str, ...]) -> None:
        self._index[rel_path] = dict(node)
        if node.get("type") == "dir":
            for child in node.get("children", []):
                name = child.get("name")
                if not name:
                    continue
                self._build_index(child, rel_path + (name,))

    def get_node(self, rel_path: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
        return self._index.get(rel_path)

    def list_dir(self, rel_path: Tuple[str, ...]) -> Optional[Iterable[Dict[str, Any]]]:
        node = self.get_node(rel_path)
        if not node or node.get("type") != "dir":
            return None
        return list(node.get("children", []))
