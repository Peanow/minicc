"""Project-level skills - load domain instructions into the system prompt.

Each skill is a Markdown file under ``.corecoder/skills/`` with optional
YAML frontmatter::

    ---
    name: my-skill
    description: Short description for /skills listing
    ---

    Skill body goes here — it will be injected into the system prompt
    so the LLM follows these domain-specific instructions.

If the frontmatter is missing the file name (sans ``.md``) becomes the
skill name and the description defaults to an empty string.

Skills are discovered at startup by walking from *cwd* upward to the
home directory looking for a ``.corecoder/skills/`` directory.  The
closest match wins (same strategy as ``config.py`` uses for ``.env``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKILLS_DIR_NAME = ".corecoder"
_SKILLS_SUBDIR = "skills"

# ---------------------------------------------------------------------------
# Frontmatter parser (tiny — no PyYAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\n(.*?)\n?---[ \t]*\n?", re.DOTALL
)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body) from *text*.

    Only parses simple ``key: value`` lines.  No nested structures,
    lists, or quoting — keeps the dependency surface at zero.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw = m.group(1)
    body = text[m.end():]

    # Handle empty frontmatter (---\n---)
    if not raw.strip():
        return {}, body

    meta: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    return meta, body


# ---------------------------------------------------------------------------
# Skill data structure
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """A single skill definition loaded from disk."""

    name: str
    description: str
    content: str
    source_path: Path = field(default_factory=lambda: Path("."))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_skill(path: Path) -> Skill:
    """Parse a single skill Markdown file."""
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    name = meta.get("name", path.stem)
    description = meta.get("description", "")

    return Skill(
        name=name,
        description=description,
        content=body.strip(),
        source_path=path,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _find_skills_dir(cwd: Path) -> Path | None:
    """Walk from *cwd* upward to home, return the first ``.corecoder/skills/``."""
    home = Path.home()
    cur = cwd.resolve()
    while True:
        candidate = cur / _SKILLS_DIR_NAME / _SKILLS_SUBDIR
        if candidate.is_dir():
            return candidate
        if cur == home or cur == cur.parent:
            break
        cur = cur.parent
    return None


def discover_skills(cwd: str | Path | None = None) -> list[Skill]:
    """Discover and load all project-level skills.

    Returns an empty list when no ``.corecoder/skills/`` directory exists.
    """
    start = Path(cwd) if cwd else Path.cwd()
    skills_dir = _find_skills_dir(start)
    if skills_dir is None:
        return []

    skills: list[Skill] = []
    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            skills.append(load_skill(md_file))
        except Exception:
            # skip unreadable / malformed skills silently
            continue
    return skills


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_skills_prompt(skills: list[Skill]) -> str:
    """Render *skills* as a section suitable for the system prompt."""
    if not skills:
        return ""

    parts: list[str] = ["# Skills"]
    for skill in skills:
        parts.append(f"## {skill.name}")
        if skill.description:
            parts.append(skill.description)
        parts.append(skill.content)

    return "\n\n".join(parts)
