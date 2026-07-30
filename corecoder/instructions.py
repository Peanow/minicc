"""Layered project instructions compatible with AGENTS.md conventions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_BYTES = 32 * 1024


@dataclass(frozen=True)
class InstructionSource:
    path: Path
    content: str
    source_bytes: int
    loaded_bytes: int

    @property
    def truncated(self) -> bool:
        return self.loaded_bytes < self.source_bytes


def find_project_root(cwd: str | Path | None = None) -> Path:
    """Return the closest Git root, or the current directory."""
    start = (Path(cwd) if cwd else Path.cwd()).expanduser().resolve()
    current = start
    while True:
        if (current / ".git").exists():
            return current
        if current == current.parent:
            return start
        current = current.parent


def _path_chain(root: Path, cwd: Path) -> list[Path]:
    if root == cwd:
        return [root]
    relative = cwd.relative_to(root)
    chain = [root]
    current = root
    for part in relative.parts:
        current = current / part
        chain.append(current)
    return chain


def load_project_instructions(
    cwd: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    project_root: str | Path | None = None,
) -> list[InstructionSource]:
    """Load one instruction file per directory from project root to cwd.

    ``AGENTS.override.md`` wins over ``AGENTS.md`` in the same directory.
    For compatibility with this repository's upstream layout, ``CLAUDE.md`` is
    used only at the project root when neither AGENTS file exists there.
    """
    current = (Path(cwd) if cwd else Path.cwd()).expanduser().resolve()
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else find_project_root(current)
    )
    try:
        current.relative_to(root)
    except ValueError as exc:
        raise ValueError("cwd must be inside project_root") from exc
    sources: list[InstructionSource] = []
    used_bytes = 0

    for directory in _path_chain(root, current):
        candidates = [
            directory / "AGENTS.override.md",
            directory / "AGENTS.md",
        ]
        if directory == root:
            candidates.append(directory / "CLAUDE.md")

        selected = next(
            (path for path in candidates if path.is_file() and path.stat().st_size),
            None,
        )
        if selected is None:
            continue

        remaining = max_bytes - used_bytes
        if remaining <= 0:
            break
        source_bytes = selected.stat().st_size
        raw = selected.read_bytes()[:remaining]
        content = raw.decode("utf-8", errors="replace").strip()
        if not content:
            continue
        used_bytes += len(raw)
        sources.append(InstructionSource(
            path=selected,
            content=content,
            source_bytes=source_bytes,
            loaded_bytes=len(raw),
        ))

    return sources


def format_project_instructions(sources: list[InstructionSource]) -> str:
    if not sources:
        return ""
    sections = ["# Project Instructions"]
    for source in sources:
        sections.append(f"## Source: {source.path}\n\n{source.content}")
    return "\n\n".join(sections)
