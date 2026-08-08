"""Application-owned paths and stable project identification.

Runtime components should receive an :class:`AppPaths` instance instead of
reaching into ``Path.home()`` themselves.  This keeps persistence isolated per
agent/application instance and makes tests safe to run without touching the
real CoreCoder home directory.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def normalize_project_root(workspace: str | os.PathLike[str] | None = None) -> Path:
    """Return the canonical Git root for *workspace*, or the workspace itself.

    Looking for a ``.git`` file as well as a directory supports linked
    worktrees and submodules without invoking Git (and therefore without
    inheriting process-global Git configuration or spawning a subprocess).
    """

    start = Path.cwd() if workspace is None else Path(workspace)
    start = start.expanduser().resolve(strict=False)
    if start.is_file():
        start = start.parent

    current = start
    while True:
        if (current / ".git").exists():
            return current
        if current == current.parent:
            return start
        current = current.parent


def project_id_for(workspace: str | os.PathLike[str] | None = None) -> str:
    """Create a stable, non-reversible identifier for a normalized project."""

    root = normalize_project_root(workspace)
    canonical = unicodedata.normalize("NFC", os.path.normcase(str(root)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ProjectPaths:
    """Application paths scoped to one normalized project root."""

    app_root: Path
    workspace_root: Path
    project_id: str

    @property
    def project_dir(self) -> Path:
        return self.app_root / "projects" / self.project_id

    @property
    def sessions_dir(self) -> Path:
        return self.project_dir / "sessions"

    @property
    def history_dir(self) -> Path:
        return self.project_dir / "history"

    @property
    def history_path(self) -> Path:
        """Directory reserved for terminal histories and related metadata."""

        return self.history_dir

    @property
    def history_file(self) -> Path:
        return self.history_dir / "prompt.history"

    @property
    def memory_dir(self) -> Path:
        return self.project_dir / "memory"

    @property
    def trace_dir(self) -> Path:
        return self.project_dir / "trace"

    # Short aliases make composition code readable while the ``*_dir`` names
    # remain explicit for callers that need to distinguish files/directories.
    @property
    def sessions(self) -> Path:
        return self.sessions_dir

    @property
    def history(self) -> Path:
        return self.history_dir

    @property
    def memory(self) -> Path:
        return self.memory_dir

    @property
    def trace(self) -> Path:
        return self.trace_dir


class AppPaths:
    """Resolve all CoreCoder-owned files from one injectable root.

    ``root`` defaults to ``CORECODER_HOME`` when set, otherwise
    ``~/.corecoder``.  Merely constructing this object never creates files or
    directories.
    """

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        configured = root if root is not None else os.getenv("CORECODER_HOME")
        if configured is None:
            configured = Path.home() / ".corecoder"
        self.root = Path(configured).expanduser().resolve(strict=False)

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def projects(self) -> Path:
        return self.projects_dir

    def project_id(self, workspace: str | os.PathLike[str] | None = None) -> str:
        return project_id_for(workspace)

    def project_hash(self, workspace: str | os.PathLike[str] | None = None) -> str:
        """Compatibility spelling for callers that expose the hash in UI."""

        return self.project_id(workspace)

    def for_project(
        self, workspace: str | os.PathLike[str] | None = None
    ) -> ProjectPaths:
        workspace_root = normalize_project_root(workspace)
        return ProjectPaths(
            app_root=self.root,
            workspace_root=workspace_root,
            project_id=project_id_for(workspace_root),
        )

    def project_paths(
        self, workspace: str | os.PathLike[str] | None = None
    ) -> ProjectPaths:
        return self.for_project(workspace)

    def project(
        self, workspace: str | os.PathLike[str] | None = None
    ) -> ProjectPaths:
        """Short alias for composition roots."""

        return self.for_project(workspace)

    def project_dir(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.for_project(workspace).project_dir

    def sessions_dir(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.for_project(workspace).sessions_dir

    def sessions(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.sessions_dir(workspace)

    def history_path(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.for_project(workspace).history_path

    def history(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.history_path(workspace)

    def memory_dir(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.for_project(workspace).memory_dir

    def memory(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.memory_dir(workspace)

    def trace_dir(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.for_project(workspace).trace_dir

    def trace(self, workspace: str | os.PathLike[str] | None = None) -> Path:
        return self.trace_dir(workspace)


__all__ = [
    "AppPaths",
    "ProjectPaths",
    "normalize_project_root",
    "project_id_for",
]
