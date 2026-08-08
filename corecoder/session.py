"""Project-scoped, atomic session persistence.

The v2 store is deliberately instance-owned.  It receives :class:`AppPaths`
and a workspace, keeps projects isolated, and never relies on a module-global
store.  The functions at the end of this module are thin compatibility
adapters for the pre-0.4 CLI; new code should use :class:`SessionStore`.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import AppPaths
from .trace import redact

SCHEMA_VERSION = 2
_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9._-]+")


class SessionError(RuntimeError):
    """A session could not be read, validated, or persisted safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _new_session_id() -> str:
    return f"session_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def normalize_session_id(session_id: str | None) -> str:
    """Return a filename-safe session ID without permitting path traversal."""

    if not session_id:
        return _new_session_id()
    name = session_id.strip().replace("\\", "/").split("/")[-1]
    name = _SAFE_SESSION_RE.sub("-", name).strip(".-_")
    return name or _new_session_id()


@dataclass
class SessionRecord:
    """Serializable schema v2 session checkpoint."""

    id: str
    project_id: str
    created_at: str
    updated_at: str
    model: str
    context_strategy: str
    active_skills: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_run_status: str = "completed"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        # Keep schema_version first in the JSON for easier manual diagnosis.
        values = asdict(self)
        return {"schema_version": values.pop("schema_version"), **values}

    @classmethod
    def from_dict(cls, data: object, *, source: str = "session") -> "SessionRecord":
        if not isinstance(data, dict):
            raise SessionError(f"Unable to load {source}: expected a JSON object.")
        if data.get("schema_version") != SCHEMA_VERSION:
            found = data.get("schema_version", "missing")
            raise SessionError(
                f"Unable to load {source}: unsupported schema version {found!r}; "
                f"expected {SCHEMA_VERSION}."
            )

        string_fields = (
            "id",
            "project_id",
            "created_at",
            "updated_at",
            "model",
            "context_strategy",
            "last_run_status",
        )
        missing = [name for name in string_fields if not isinstance(data.get(name), str)]
        if missing:
            raise SessionError(
                f"Unable to load {source}: missing or invalid field(s): "
                + ", ".join(missing)
                + "."
            )
        active_skills = data.get("active_skills")
        messages = data.get("messages")
        if not isinstance(active_skills, list) or not all(
            isinstance(item, str) for item in active_skills
        ):
            raise SessionError(
                f"Unable to load {source}: 'active_skills' must be a list of strings."
            )
        if not isinstance(messages, list) or not all(
            isinstance(item, dict) for item in messages
        ):
            raise SessionError(
                f"Unable to load {source}: 'messages' must be a list of objects."
            )
        return cls(
            schema_version=SCHEMA_VERSION,
            id=data["id"],
            project_id=data["project_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            model=data["model"],
            context_strategy=data["context_strategy"],
            active_skills=list(active_skills),
            messages=[dict(message) for message in messages],
            last_run_status=data["last_run_status"],
        )


# A concise alias is convenient for public type annotations.
Session = SessionRecord


class SessionStore:
    """Persist schema v2 sessions for exactly one project."""

    schema_version = SCHEMA_VERSION

    def __init__(
        self,
        app_paths: AppPaths | None = None,
        workspace: str | os.PathLike[str] | None = None,
        *,
        sessions_dir: str | os.PathLike[str] | None = None,
        project_id: str | None = None,
    ) -> None:
        self.app_paths = app_paths or AppPaths()
        project_paths = self.app_paths.for_project(workspace)
        self.workspace_root = project_paths.workspace_root
        self.project_id = project_id or project_paths.project_id
        self.sessions_dir = (
            Path(sessions_dir).expanduser().resolve(strict=False)
            if sessions_dir is not None
            else project_paths.sessions_dir
        )

    def _path(self, session_id: str) -> Path:
        normalized = normalize_session_id(session_id)
        return self.sessions_dir / f"{normalized}.json"

    def save(
        self,
        messages: list[dict[str, Any]] | SessionRecord,
        model: str | None = None,
        session_id: str | None = None,
        *,
        context_strategy: str = "default",
        active_skills: list[str] | None = None,
        last_run_status: str = "completed",
    ) -> SessionRecord:
        """Atomically create or update a complete session checkpoint."""

        if isinstance(messages, SessionRecord):
            if model is not None or session_id is not None:
                raise TypeError("model/session_id cannot accompany a SessionRecord")
            if messages.project_id != self.project_id:
                raise SessionError("Cannot save a session that belongs to another project.")
            session_id = normalize_session_id(messages.id)
            if session_id != messages.id:
                raise SessionError("Cannot save a session with an invalid id.")
            # Saving is a new checkpoint, but it must not mutate a record held
            # by the caller (terminal state may still use it as its last good
            # checkpoint after a later cancellation).
            record = replace(
                messages,
                schema_version=SCHEMA_VERSION,
                active_skills=list(messages.active_skills),
                messages=[dict(message) for message in messages.messages],
                updated_at=_utc_now(),
            )
        else:
            if model is None:
                raise TypeError("model is required when saving messages")
            if not isinstance(messages, list) or not all(
                isinstance(message, dict) for message in messages
            ):
                raise TypeError("messages must be a list of dictionaries")
            session_id = normalize_session_id(session_id)
            existing = self.load(session_id)
            now = _utc_now()
            record = SessionRecord(
                id=session_id,
                project_id=self.project_id,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                model=model,
                context_strategy=context_strategy,
                active_skills=list(active_skills or []),
                messages=[dict(message) for message in messages],
                last_run_status=last_run_status,
            )

        # Apply the same schema validation to caller-built records as to data
        # loaded from disk, so an invalid checkpoint is never persisted.
        record = SessionRecord.from_dict(record.to_dict(), source="session checkpoint")
        payload = record.to_dict()
        # Sessions are user-visible application state, but must never become a
        # credential cache when a prompt/tool message contains an API key.
        payload["messages"] = redact(payload.get("messages", []))
        self._atomic_write(self._path(record.id), payload)
        return record

    def _atomic_write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._chmod_private(temp_path)
            os.replace(temp_path, path)
            temp_path = None
            self._chmod_private(path)
        except (OSError, TypeError, ValueError) as exc:
            raise SessionError(f"Unable to save session {path.stem!r}: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _chmod_private(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            # Best effort on filesystems/platforms without POSIX permissions.
            pass

    def load(self, session_id: str) -> SessionRecord | None:
        normalized = normalize_session_id(session_id)
        path = self._path(normalized)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionError(
                f"Unable to load session {normalized!r}: the file contains invalid JSON."
            ) from exc
        except OSError as exc:
            raise SessionError(f"Unable to load session {normalized!r}: {exc}") from exc

        record = SessionRecord.from_dict(data, source=f"session {normalized!r}")
        if record.id != normalized:
            raise SessionError(
                f"Unable to load session {normalized!r}: its stored id does not match "
                "the filename."
            )
        if record.project_id != self.project_id:
            raise SessionError(
                f"Unable to load session {normalized!r}: it belongs to a different project."
            )
        return record

    def list(self, *, limit: int | None = None) -> list[SessionRecord]:
        """Return project sessions ordered by most recent update."""

        if not self.sessions_dir.exists():
            return []
        records: list[SessionRecord] = []
        for path in self.sessions_dir.glob("*.json"):
            record = self.load(path.stem)
            if record is not None:
                records.append(record)
        records.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            return records[:limit]
        return records

    def list_sessions(self, *, limit: int | None = None) -> list[SessionRecord]:
        return self.list(limit=limit)

    def latest(self) -> SessionRecord | None:
        records = self.list(limit=1)
        return records[0] if records else None

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SessionError(
                f"Unable to delete session {normalize_session_id(session_id)!r}: {exc}"
            ) from exc
        return True


# ---------------------------------------------------------------------------
# Pre-0.4 function compatibility
# ---------------------------------------------------------------------------

# This immutable path constant exists only so older callers/tests can redirect
# the compatibility functions.  No SessionStore or session data lives at module
# scope.  New code must inject AppPaths into SessionStore instead.
SESSIONS_DIR = Path.home() / ".corecoder" / "sessions"


def _compat_store() -> SessionStore:
    return SessionStore(sessions_dir=SESSIONS_DIR, project_id="legacy")


def save_session(
    messages: list[dict[str, Any]], model: str, session_id: str | None = None
) -> str:
    """Compatibility adapter returning only the saved session ID."""

    return _compat_store().save(messages, model, session_id).id


def load_session(session_id: str) -> tuple[list[dict[str, Any]], str] | None:
    """Compatibility adapter returning ``(messages, model)``."""

    record = _compat_store().load(session_id)
    if record is None:
        return None
    return record.messages, record.model


def list_sessions() -> list[dict[str, Any]]:
    """Compatibility adapter matching the original CLI's summary shape."""

    summaries: list[dict[str, Any]] = []
    for record in _compat_store().list(limit=20):
        preview = ""
        for message in record.messages:
            if message.get("role") == "user" and message.get("content"):
                preview = str(message["content"])[:80]
                break
        summaries.append(
            {
                "id": record.id,
                "model": record.model,
                "saved_at": record.updated_at,
                "preview": preview,
            }
        )
    return summaries


__all__ = [
    "SCHEMA_VERSION",
    "Session",
    "SessionError",
    "SessionRecord",
    "SessionStore",
    "list_sessions",
    "load_session",
    "normalize_session_id",
    "save_session",
]
