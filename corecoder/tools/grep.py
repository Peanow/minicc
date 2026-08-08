"""Content search with regex support."""

import re
from pathlib import Path
from .base import Effect, Tool, ToolResult

# skip these dirs to avoid noise
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}


class GrepTool(Tool):
    parallel_safe = True
    effects = frozenset({Effect.READ_FS})
    name = "grep"
    description = (
        "Search file contents with regex. "
        "Returns matching lines with file path and line number."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search (default: cwd)",
            },
            "include": {
                "type": "string",
                "description": "Only search files matching this glob (e.g. '*.py')",
            },
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".", include: str | None = None) -> ToolResult:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult.error(f"Invalid regex: {e}", error_type="InvalidRegex")

        try:
            base = self.resolve_path(path, require_inside=True)
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)
        if not base.exists():
            return ToolResult.error(f"{path} not found", error_type="FileNotFoundError")

        if base.is_file():
            files = [base]
        else:
            files = self._walk(base, include)

        matches = []
        for fp in files:
            # A directory can contain symlinks that resolve outside the
            # workspace.  Keep the same resolved-path boundary as Read/Glob
            # instead of exposing those files through recursive search.
            if self.workspace is not None and not self.workspace.contains(fp):
                continue
            try:
                text = fp.read_text(errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{fp}:{lineno}: {line.rstrip()}")
                    if len(matches) >= 200:
                        matches.append("... (200 match limit reached)")
                        return ToolResult.success("\n".join(matches))

        return ToolResult.success("\n".join(matches) if matches else "No matches found.")

    @staticmethod
    def _walk(root: Path, include: str | None) -> list[Path]:
        """Walk dir tree, skipping junk dirs."""
        results = []
        for item in root.rglob(include or "*"):
            # skip hidden/junk directories
            if any(part in _SKIP_DIRS for part in item.parts):
                continue
            if item.is_file():
                results.append(item)
            if len(results) >= 5000:
                break
        return results
