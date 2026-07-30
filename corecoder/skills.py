"""Project-level skills with progressive disclosure.

The preferred layout follows the open Agent Skills convention:
``.agents/skills/<name>/SKILL.md``. The former flat
``.corecoder/skills/*.md`` layout remains available as a compatibility path.

    ---
    name: my-skill
    description: Short description for /skills listing
    ---

    Skill body goes here — it will be injected into the conversation
    when the user invokes ``/skill my-skill``, so the LLM follows
    these domain-specific instructions for the rest of the session.

**On-demand loading:** the system prompt only contains a lightweight
directory (name + description).  The full skill content is injected as a
user message only when the skill is explicitly invoked via the ``/skill``
command, saving context window space.

If the frontmatter is missing the file name (sans ``.md``) becomes the
skill name and the description defaults to an empty string.

Standard skill directories are layered from the Git root down to the current
directory. A closer skill with the same name overrides its parent definition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from .instructions import find_project_root

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

    default_name = path.parent.name if path.name == "SKILL.md" else path.stem
    name = meta.get("name", default_name)
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

def _find_skills_dir(cwd: Path, stop_at: Path | None = None) -> Path | None:
    """Walk from *cwd* upward to home, return the first ``.corecoder/skills/``."""
    home = Path.home()
    cur = cwd.resolve()
    while True:
        candidate = cur / _SKILLS_DIR_NAME / _SKILLS_SUBDIR
        if candidate.is_dir():
            return candidate
        if cur == stop_at or cur == home or cur == cur.parent:
            break
        cur = cur.parent
    return None


def discover_skills(
    cwd: str | Path | None = None,
    project_root: str | Path | None = None,
) -> list[Skill]:
    """Discover and load all project-level skills.

    Standard skills are preferred. If none exist, load the nearest legacy
    ``.corecoder/skills`` directory for backward compatibility.
    """
    start = (Path(cwd) if cwd else Path.cwd()).expanduser().resolve()
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else find_project_root(start)
    )
    try:
        start.relative_to(root)
    except ValueError as exc:
        raise ValueError("cwd must be inside project_root") from exc
    directories = [root]
    current = root
    if start != root:
        for part in start.relative_to(root).parts:
            current = current / part
            directories.append(current)

    by_name: dict[str, Skill] = {}
    for directory in directories:
        standard_root = directory / ".agents" / "skills"
        if not standard_root.is_dir():
            continue
        for skill_file in sorted(standard_root.glob("*/SKILL.md")):
            try:
                skill = load_skill(skill_file)
                by_name[skill.name.lower()] = skill
            except Exception:
                continue

    if by_name:
        return sorted(by_name.values(), key=lambda skill: skill.name.lower())

    legacy_dir = _find_skills_dir(
        start,
        stop_at=root if project_root is not None else None,
    )
    if legacy_dir is None:
        return []
    for md_file in sorted(legacy_dir.glob("*.md")):
        try:
            skill = load_skill(md_file)
            by_name[skill.name.lower()] = skill
        except Exception:
            continue
    return sorted(by_name.values(), key=lambda skill: skill.name.lower())


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_skills_directory(skills: list[Skill], max_chars: int = 8_000) -> str:
    """Render a lightweight skill *directory* for the system prompt.

    Only includes names and descriptions — the full content is withheld
    until the user invokes ``/skill <name>``.  This keeps the system
    prompt small while still telling the model what skills exist.
    """
    if not skills:
        return ""

    lines: list[str] = [
        "# Skills",
        "The following skills are available. Use the `skill` tool to activate one when relevant to the user's request.",
    ]
    for skill in skills:
        desc = f": {skill.description}" if skill.description else ""
        source = (
            f" ({skill.source_path})"
            if skill.source_path != Path(".")
            else ""
        )
        candidate = f"- **{skill.name}**{desc}{source}"
        if len("\n".join(lines + [candidate])) > max_chars:
            lines.append("- ... additional skills omitted to preserve context budget")
            break
        lines.append(candidate)

    return "\n".join(lines)


def format_skill_invocation(skill: Skill) -> str:
    """Render the full content of *skill* for injection as a user message.

    Called only when the user explicitly invokes a skill via
    ``/skill <name>``.
    """
    return f"[Skill: {skill.name}]\n\n{skill.content}"


def find_skill_by_name(skills: list[Skill], name: str) -> Skill | None:
    """Look up a skill by name (case-insensitive)."""
    name_lower = name.lower()
    for skill in skills:
        if skill.name.lower() == name_lower:
            return skill
    return None
