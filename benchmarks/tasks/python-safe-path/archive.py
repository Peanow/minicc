from pathlib import Path


def resolve_member(root: str | Path, member: str) -> Path:
    """Resolve an archive member below root."""
    return Path(root).resolve() / member
