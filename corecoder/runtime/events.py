"""Typed, in-process events shared by the runtime and terminal adapters."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol


class EventKind(str, Enum):
    RUN_STARTED = "run_started"
    TEXT_DELTA = "text_delta"
    MODEL_STARTED = "model_started"
    MODEL_FINISHED = "model_finished"
    MODEL_FAILED = "model_failed"
    TOOL_REQUESTED = "tool_requested"
    APPROVAL_REQUESTED = "approval_requested"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    CONTEXT_COMPACTED = "context_compacted"
    RUN_FINISHED = "run_finished"


@dataclass(frozen=True)
class RunEvent:
    """One observable runtime transition.

    The payload is deliberately JSON-compatible so the same event can be
    rendered interactively or serialized as JSONL without another adapter.
    """

    kind: EventKind | str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    schema: int = 2

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event"] = str(self.kind.value if isinstance(self.kind, EventKind) else self.kind)
        value.pop("kind", None)
        return value


class RunObserver(Protocol):
    """Consumer for live run events."""

    def on_event(self, event: RunEvent) -> None:
        ...


def notify(observer: RunObserver | None, event: RunEvent) -> None:
    """Deliver an event without allowing UI failures to corrupt a run."""

    if observer is None:
        return
    try:
        if hasattr(observer, "on_event"):
            observer.on_event(event)
        elif hasattr(observer, "emit"):
            observer.emit(event)
        elif callable(observer):
            observer(event)
    except Exception:
        # A renderer/automation observer is an output adapter, not runtime
        # authority. Persistent trace failures are handled by TraceSink.
        return
