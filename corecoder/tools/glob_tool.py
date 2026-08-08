"""File pattern matching."""

from .base import Effect, Tool, ToolResult


class GlobTool(Tool):
    parallel_safe = True
    effects = frozenset({Effect.READ_FS})
    name = "glob"
    description = (
        "Find files matching a glob pattern. "
        "Supports ** for recursive matching (e.g. '**/*.py')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: cwd)",
            },
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".") -> ToolResult:
        try:
            base = self.resolve_path(path, require_inside=True)
            if not base.is_dir():
                return ToolResult.error(
                    f"{path} is not a directory",
                    error_type="NotADirectoryError",
                )

            hits = [
                hit for hit in base.glob(pattern)
                if self.workspace is None or self.workspace.contains(hit)
            ]
            # sort by mtime, newest first
            hits.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

            total = len(hits)
            shown = hits[:100]
            lines = [str(h) for h in shown]
            result = "\n".join(lines)

            if total > 100:
                result += f"\n... ({total} matches, showing first 100)"
            return ToolResult.success(result or "No files matched.")
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)
