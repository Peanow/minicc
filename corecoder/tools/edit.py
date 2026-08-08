"""Search-and-replace file editing (Claude Code's key innovation).

The core idea: instead of sending whole-file rewrites or line-number patches,
the LLM specifies an *exact* substring to find and its replacement. The
substring must appear exactly once in the file, which eliminates ambiguity
and makes edits safe and reviewable.
"""

import difflib

from .base import Effect, Tool, ToolResult


class EditFileTool(Tool):
    effects = frozenset({Effect.WRITE_FS})
    name = "edit_file"
    description = (
        "Edit a file by replacing an exact string match. "
        "old_string must appear exactly once in the file for safety. "
        "Include enough surrounding context to ensure uniqueness."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find (must be unique in file)",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def __init__(self, changed_files: set[str] | None = None, workspace=None):
        super().__init__(workspace)
        self.changed_files = changed_files if changed_files is not None else set()

    def execute(self, file_path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            p = self.resolve_path(file_path, require_inside=True)
            if not p.exists():
                return ToolResult.error(f"{file_path} not found", error_type="FileNotFoundError")

            content = p.read_text()
            occurrences = content.count(old_string)

            if occurrences == 0:
                preview = content[:500] + ("..." if len(content) > 500 else "")
                return ToolResult.error(
                    f"old_string not found in {file_path}.\nFile starts with:\n{preview}",
                    error_type="MatchNotFound",
                )
            if occurrences > 1:
                return ToolResult.error(
                    f"old_string appears {occurrences} times in {file_path}. "
                    "Include more surrounding lines to make it unique.",
                    error_type="AmbiguousMatch",
                )

            new_content = content.replace(old_string, new_string, 1)
            p.write_text(new_content)
            self.changed_files.add(str(p))

            # generate a unified diff so the user/LLM can see exactly what changed
            diff = _unified_diff(content, new_content, str(p))
            return ToolResult.success(
                f"Edited {file_path}\n{diff}",
                changed_files=(str(p),),
                diff=diff or None,
            )
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)


def _unified_diff(old: str, new: str, filename: str, context: int = 3) -> str:
    """Generate a compact unified diff between old and new file content."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
        n=context,
    )
    result = "".join(diff)
    # truncate enormous diffs
    if len(result) > 3000:
        result = result[:2500] + "\n... (diff truncated)\n"
    return result
