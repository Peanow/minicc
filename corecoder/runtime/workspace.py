"""Single source of truth for workspace and logical working-directory paths."""

from __future__ import annotations

import threading
from pathlib import Path


class WorkspaceError(ValueError):
    pass


class WorkspaceState:
    """Agent-owned workspace root and mutable logical cwd.

    Side-effecting cwd changes are serialized. Read-only path resolution takes
    a snapshot under the same lock so tools and policy authorize the same path.
    """

    def __init__(self, root: str | Path, cwd: str | Path | None = None):
        self.root = Path(root).expanduser().resolve()
        initial = Path(cwd).expanduser() if cwd is not None else self.root
        if not initial.is_absolute():
            initial = self.root / initial
        self._cwd = initial.resolve()
        self._lock = threading.RLock()
        self._assert_inside(self._cwd)

    @property
    def cwd(self) -> Path:
        with self._lock:
            return self._cwd

    def resolve(self, value: str | Path, *, require_inside: bool = False) -> Path:
        candidate = Path(value).expanduser()
        with self._lock:
            if not candidate.is_absolute():
                candidate = self._cwd / candidate
            resolved = candidate.resolve(strict=False)
        if require_inside:
            self._assert_inside(resolved)
        return resolved

    def contains(self, value: str | Path) -> bool:
        try:
            self.resolve(value, require_inside=True)
            return True
        except WorkspaceError:
            return False

    def chdir(self, value: str | Path) -> Path:
        target = self.resolve(value, require_inside=True)
        if not target.is_dir():
            raise WorkspaceError(f"working directory does not exist: {target}")
        with self._lock:
            self._cwd = target
        return target

    def _assert_inside(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(f"path is outside workspace: {path}") from exc
