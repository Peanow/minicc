"""Structured execution traces for debugging and evaluation."""

from __future__ import annotations

import json
import hashlib
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


def _canonicalize_workspace(value: Any, workspace: str | Path) -> Any:
    """Replace workspace-specific absolute paths before stable hashing."""
    root = str(Path(workspace).expanduser().resolve())
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_workspace(item, root)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_workspace(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(root, "${WORKSPACE}")
    return value


def request_fingerprint(
    messages: list[dict],
    tools: list[dict],
    workspace: str | Path,
) -> str:
    """Hash a canonical model request without persisting its full contents."""
    payload = _canonicalize_workspace(
        {"messages": messages, "tools": tools},
        workspace,
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TraceSink:
    """Minimal trace output interface."""

    run_id: str
    session_id: str

    def begin_run(self, run_id: str | None = None) -> str:
        """Start one user task and return its run identifier."""
        self.run_id = run_id or uuid.uuid4().hex
        return self.run_id

    def emit(self, event: str, **data):
        raise NotImplementedError

    def end_run(self, status: str = "completed"):
        """Finish the active user task."""
        pass

    def close(self):
        pass


class NullTraceSink(TraceSink):
    """No-op sink used when tracing is disabled."""

    def __init__(self):
        self.run_id = ""
        self.session_id = ""

    def begin_run(self, run_id: str | None = None) -> str:
        return ""

    def emit(self, event: str, **data):
        pass


class InMemoryTraceSink(TraceSink):
    """Trace sink for tests and library integrations."""

    def __init__(
        self,
        run_id: str | None = None,
        session_id: str | None = None,
    ):
        self.run_id = run_id or uuid.uuid4().hex
        self.session_id = session_id or uuid.uuid4().hex
        self._initial_run_id = run_id
        self._run_count = 0
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def begin_run(self, run_id: str | None = None) -> str:
        if run_id is None and self._run_count == 0 and self._initial_run_id:
            run_id = self._initial_run_id
        self.run_id = run_id or uuid.uuid4().hex
        self._run_count += 1
        return self.run_id

    def emit(self, event: str, **data):
        record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "timestamp": time.time(),
            "event": event,
            "data": redact(data),
        }
        with self._lock:
            self.events.append(record)


class JsonlTraceSink(TraceSink):
    """Append-only JSONL trace that remains useful after interrupted runs."""

    def __init__(
        self,
        path: str | Path,
        run_id: str | None = None,
        session_id: str | None = None,
    ):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex
        self.session_id = session_id or uuid.uuid4().hex
        self._initial_run_id = run_id
        self._run_count = 0
        self._file = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def begin_run(self, run_id: str | None = None) -> str:
        if run_id is None and self._run_count == 0 and self._initial_run_id:
            run_id = self._initial_run_id
        self.run_id = run_id or uuid.uuid4().hex
        self._run_count += 1
        return self.run_id

    def emit(self, event: str, **data):
        record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "session_id": self.session_id,
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


class CompositeTraceSink(TraceSink):
    """Fan trace events out to independent sinks without coupling failures."""

    def __init__(
        self,
        sinks: list[TraceSink] | None = None,
        session_id: str | None = None,
    ):
        self.session_id = session_id or uuid.uuid4().hex
        self.run_id = ""
        self._sinks: list[TraceSink] = []
        self._lock = threading.Lock()
        for sink in sinks or []:
            self.add_sink(sink)

    @property
    def sinks(self) -> tuple[TraceSink, ...]:
        with self._lock:
            return tuple(self._sinks)

    def add_sink(self, sink: TraceSink) -> bool:
        with self._lock:
            if sink in self._sinks:
                return False
            sink.session_id = self.session_id
            self._sinks.append(sink)
        return True

    def begin_run(self, run_id: str | None = None) -> str:
        self.run_id = run_id or uuid.uuid4().hex
        for sink in self.sinks:
            try:
                sink.begin_run(self.run_id)
            except Exception:
                continue
        return self.run_id

    def emit(self, event: str, **data):
        for sink in self.sinks:
            try:
                sink.emit(event, **data)
            except Exception:
                continue

    def end_run(self, status: str = "completed"):
        for sink in self.sinks:
            try:
                sink.end_run(status)
            except Exception:
                continue

    def close(self):
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:
                continue


def _attribute_value(value: Any) -> str | int | float | bool:
    """Convert arbitrary redacted values into valid bounded OTel attributes."""
    safe = redact(value)
    if isinstance(safe, (str, int, float, bool)):
        return safe
    # Redact once more after serialization so a large collection of individually
    # small messages cannot create an unbounded OTLP attribute.
    return redact(json.dumps(safe, ensure_ascii=False, default=str))


class OpenTelemetryTraceSink(TraceSink):
    """Translate CoreCoder events into portable OpenTelemetry spans.

    OpenTelemetry remains an optional dependency. Importing ``corecoder.trace``
    never requires the observability extra.
    """

    def __init__(
        self,
        endpoint: str,
        project_name: str = "corecoder",
        content_policy: str = "full",
        session_id: str | None = None,
        exporter=None,
    ):
        if content_policy not in {"full", "metadata-only"}:
            raise ValueError("content_policy must be 'full' or 'metadata-only'")
        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            if exporter is None:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                exporter = OTLPSpanExporter(endpoint=endpoint, timeout=5)
        except ImportError as exc:
            raise RuntimeError(
                'OpenTelemetry support is not installed. Run: pip install "corecoder[observability]"'
            ) from exc

        self.endpoint = endpoint
        self.project_name = project_name
        self.content_policy = content_policy
        self.session_id = session_id or uuid.uuid4().hex
        self.run_id = ""
        self._otel_trace = otel_trace
        self._provider = TracerProvider(resource=Resource.create({
            "service.name": "corecoder",
            "openinference.project.name": project_name,
        }))
        self._processor = BatchSpanProcessor(exporter, schedule_delay_millis=500)
        self._provider.add_span_processor(self._processor)
        self._tracer = self._provider.get_tracer("corecoder")
        self._root = None
        self._model = "unknown"
        self._llm_spans: dict[int, Any] = {}
        self._tool_spans: dict[str, Any] = {}
        self._pending_tool_data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._closed = False

    def _root_context(self):
        if self._root is None:
            return None
        return self._otel_trace.set_span_in_context(self._root)

    def _set(self, span, name: str, value: Any):
        if span is not None and value is not None:
            span.set_attribute(name, _attribute_value(value))

    def begin_run(self, run_id: str | None = None) -> str:
        with self._lock:
            if self._root is not None:
                self.end_run("interrupted")
            self.run_id = run_id or uuid.uuid4().hex
            self._root = self._tracer.start_span("invoke_agent corecoder")
            self._root.set_attribute("openinference.span.kind", "AGENT")
            self._root.set_attribute("gen_ai.operation.name", "invoke_agent")
            self._root.set_attribute("gen_ai.agent.name", "corecoder")
            self._root.set_attribute("corecoder.run.id", self.run_id)
            self._root.set_attribute("session.id", self.session_id)
            self._root.set_attribute("openinference.project.name", self.project_name)
            self._llm_spans.clear()
            self._tool_spans.clear()
            self._pending_tool_data.clear()
        return self.run_id

    def emit(self, event: str, **data):
        safe = redact(data)
        with self._lock:
            if event == "run_started":
                self._model = str(safe.get("model") or "unknown")
                self._set(self._root, "gen_ai.request.model", safe.get("model"))
                self._set(self._root, "corecoder.context.strategy", safe.get("context_strategy"))
                self._set(self._root, "corecoder.permission.mode", safe.get("permission_mode"))
                if self.content_policy == "full":
                    self._set(self._root, "input.value", safe.get("user_input"))
                    self._set(self._root, "input.mime_type", "text/plain")
                return

            if event == "llm_started":
                round_index = int(safe.get("round") or 0)
                model = safe.get("model") or self._model
                span = self._tracer.start_span(
                    f"chat {model}", context=self._root_context(),
                )
                span.set_attribute("openinference.span.kind", "LLM")
                span.set_attribute("gen_ai.operation.name", "chat")
                self._set(span, "gen_ai.request.model", model)
                self._set(span, "corecoder.round", round_index)
                self._set(span, "corecoder.request.fingerprint", safe.get("request_fingerprint"))
                if self.content_policy == "full":
                    self._set(span, "input.value", {
                        "messages": safe.get("messages") or [],
                        "tools": safe.get("tool_definitions") or [],
                    })
                    self._set(span, "input.mime_type", "application/json")
                self._llm_spans[round_index] = span
                return

            if event == "llm_finished":
                round_index = int(safe.get("round") or 0)
                span = self._llm_spans.pop(round_index, None)
                if span is None:
                    return
                self._set(span, "gen_ai.usage.input_tokens", safe.get("prompt_tokens", 0))
                self._set(span, "gen_ai.usage.output_tokens", safe.get("completion_tokens", 0))
                self._set(span, "corecoder.duration_ms", safe.get("duration_ms", 0))
                if self.content_policy == "full":
                    self._set(span, "output.value", {
                        "content": safe.get("content"),
                        "tool_calls": safe.get("tool_calls") or [],
                    })
                    self._set(span, "output.mime_type", "application/json")
                span.end()
                return

            tool_call_id = str(safe.get("tool_call_id") or "")
            if event == "policy_decision":
                pending = self._pending_tool_data.setdefault(tool_call_id, {})
                pending.update({
                    "corecoder.policy.decision": safe.get("decision"),
                    "corecoder.policy.reason": safe.get("reason"),
                    "corecoder.policy.risk": safe.get("risk"),
                })
                span = self._tool_spans.get(tool_call_id)
                if span:
                    for key, value in pending.items():
                        self._set(span, key, value)
                if self._root is not None:
                    self._root.add_event("policy_decision", attributes={
                        "gen_ai.tool.call.id": tool_call_id,
                        "gen_ai.tool.name": str(safe.get("tool") or ""),
                        **{
                            key: _attribute_value(value)
                            for key, value in pending.items()
                            if value is not None
                        },
                    })
                return

            if event == "tool_started":
                tool = str(safe.get("tool") or "unknown")
                span = self._tracer.start_span(
                    f"execute_tool {tool}", context=self._root_context(),
                )
                span.set_attribute("openinference.span.kind", "TOOL")
                span.set_attribute("gen_ai.operation.name", "execute_tool")
                span.set_attribute("gen_ai.tool.name", tool)
                self._set(span, "gen_ai.tool.call.id", tool_call_id)
                self._set(span, "corecoder.round", safe.get("round"))
                if self.content_policy == "full":
                    self._set(span, "input.value", safe.get("arguments") or {})
                    self._set(span, "input.mime_type", "application/json")
                for key, value in self._pending_tool_data.pop(tool_call_id, {}).items():
                    self._set(span, key, value)
                self._tool_spans[tool_call_id] = span
                return

            if event == "tool_finished":
                span = self._tool_spans.pop(tool_call_id, None)
                if span is None:
                    return
                self._set(span, "corecoder.duration_ms", safe.get("duration_ms", 0))
                if self.content_policy == "full":
                    self._set(span, "output.value", safe.get("output"))
                    self._set(span, "output.mime_type", "text/plain")
                span.end()
                return

            if event == "run_finished":
                self._set(self._root, "corecoder.run.status", safe.get("status"))
                self._set(self._root, "corecoder.changed_files", safe.get("changed_files") or [])
                self._set(self._root, "error.type", safe.get("error_type"))
                if safe.get("error_type") and self._root is not None:
                    from opentelemetry.trace import Status, StatusCode
                    self._root.set_status(Status(StatusCode.ERROR, str(safe.get("error"))))
                if self.content_policy == "full":
                    self._set(self._root, "output.value", safe.get("final_answer"))
                return

            if self._root is not None:
                attrs = {
                    f"corecoder.{key}": _attribute_value(value)
                    for key, value in safe.items()
                }
                self._root.add_event(event, attributes=attrs)

    def end_run(self, status: str = "completed"):
        with self._lock:
            if status in {"error", "cancelled", "interrupted"}:
                from opentelemetry.trace import Status, StatusCode
                child_status = Status(StatusCode.ERROR, status)
                for span in self._llm_spans.values():
                    span.set_status(child_status)
                for span in self._tool_spans.values():
                    span.set_status(child_status)
            for span in self._llm_spans.values():
                span.end()
            for span in self._tool_spans.values():
                span.end()
            self._llm_spans.clear()
            self._tool_spans.clear()
            if self._root is not None:
                self._root.set_attribute("corecoder.run.status", status)
                if status in {"error", "cancelled", "interrupted"}:
                    self._root.set_status(Status(StatusCode.ERROR, status))
                self._root.end()
                self._root = None

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.end_run("closed")
        self._provider.force_flush(timeout_millis=5000)
        self._provider.shutdown()


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
