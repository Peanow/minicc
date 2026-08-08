"""File reading with line numbers."""

from .base import Effect, Tool, ToolResult


class ReadFileTool(Tool):
    parallel_safe = True
    effects = frozenset({Effect.READ_FS})
    name = "read_file"
    description = (
        "Read a file's contents with line numbers. "
        "Always read a file before editing it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file",
            },
            "offset": {
                "type": "integer",
                "description": "Start line (1-based). Default 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Max lines to read. Default 2000.",
            },
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
        try:
            p = self.resolve_path(file_path, require_inside=True)
            if not p.exists():
                return ToolResult.error(f"{file_path} not found", error_type="FileNotFoundError")
            if not p.is_file():
                return ToolResult.error(
                    f"{file_path} is a directory, not a file",
                    error_type="IsADirectoryError",
                )

            text = p.read_text(errors="replace")
            lines = text.splitlines()
            total = len(lines)

            start = max(0, offset - 1)
            chunk = lines[start : start + limit]
            numbered = [f"{start + i + 1}\t{ln}" for i, ln in enumerate(chunk)]
            result = "\n".join(numbered)

            if total > start + limit:
                result += f"\n... ({total} lines total, showing {start+1}-{start+len(chunk)})"
            return ToolResult.success(result or "(empty file)")
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)
