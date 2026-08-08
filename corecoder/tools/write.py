"""File creation / overwrite."""

from .base import Effect, Tool, ToolResult
from .edit import _unified_diff


class WriteFileTool(Tool):
    effects = frozenset({Effect.WRITE_FS})
    name = "write_file"
    description = (
        "Create a new file or completely overwrite an existing one. "
        "For small edits to existing files, prefer edit_file instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path for the file",
            },
            "content": {
                "type": "string",
                "description": "Full file content to write",
            },
        },
        "required": ["file_path", "content"],
    }

    def __init__(self, changed_files: set[str] | None = None, workspace=None):
        super().__init__(workspace)
        self.changed_files = changed_files if changed_files is not None else set()

    def execute(self, file_path: str, content: str) -> ToolResult:
        try:
            p = self.resolve_path(file_path, require_inside=True)
            old_content = p.read_text(errors="replace") if p.exists() else ""
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            self.changed_files.add(str(p))
            n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            diff = _unified_diff(old_content, content, str(p))
            return ToolResult.success(
                f"Wrote {n_lines} lines to {file_path}\n{diff}".rstrip(),
                changed_files=(str(p),),
                diff=diff or None,
            )
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)
