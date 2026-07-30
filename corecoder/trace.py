"""Structured execution traces for debugging and evaluation."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]+=*\b"),
    re.compile(r"(?i)(api[_-]?key|password|token)(\s*[=:]\s*)([^\s,;]+)"),
)


def redact(value: Any) -> Any:
    """Recursively remove common credentials before writing a trace."""
    if isinstance(value, dict):
        sensitive_keys = {
            "api_key", "authorization", "password", "access_token",
            "refresh_token", "client_secret", "secret",
        }
        return {
            str(key): (
                "[REDACTED]"
                if str(key).lower() in sensitive_keys and item
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value

    text = value
    if len(text) > 12_000:
        text = text[:8_000] + f"\n...[trace truncated: {len(value)} chars]...\n" + text[-2_000:]
    text = _SECRET_PATTERNS[0].sub("[REDACTED_API_KEY]", text)
    text = _SECRET_PATTERNS[1].sub(r"\1[REDACTED_TOKEN]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]", text)
    return text


class TraceSink:
    """Minimal trace output interface."""

    run_id: str

    def emit(self, event: str, **data):
        raise NotImplementedError

    def close(self):
        pass


class NullTraceSink(TraceSink):
    """No-op sink used when tracing is disabled."""

    def __init__(self):
        self.run_id = ""

    def emit(self, event: str, **data):
        pass


class InMemoryTraceSink(TraceSink):
    """Trace sink for tests and library integrations."""

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def emit(self, event: str, **data):
        record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "timestamp": time.time(),
            "event": event,
            "data": redact(data),
        }
        with self._lock:
            self.events.append(record)


class JsonlTraceSink(TraceSink):
    """Append-only JSONL trace that remains useful after interrupted runs."""

    def __init__(self, path: str | Path, run_id: str | None = None):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex
        self._file = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def emit(self, event: str, **data):
        record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "timestamp": time.time(),
            "event": event,
            "data": redact(data),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self):
        with self._lock:
            if not self._file.closed:
                self._file.close()


@dataclass
class RunResult:
    """Structured result returned by :meth:`Agent.run`."""

    status: str
    final_answer: str
    changed_files: list[str]
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float | None
    trace_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
