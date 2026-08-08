"""Uniform model-call gateway for agent, compaction, and memory purposes."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..trace import TraceSink, request_fingerprint
from .events import EventKind, RunEvent, RunObserver, notify


class ModelGateway:
    def __init__(
        self,
        llm,
        *,
        trace: TraceSink,
        workspace,
        observer: Callable[[], RunObserver | None],
        run_id: Callable[[], str],
    ) -> None:
        self.llm = llm
        self.trace = trace
        self.workspace = workspace
        self._observer = observer
        self._run_id = run_id

    @property
    def model(self) -> str:
        return self.llm.model

    @model.setter
    def model(self, value: str) -> None:
        self.llm.model = value

    @property
    def total_prompt_tokens(self) -> int:
        return int(getattr(self.llm, "total_prompt_tokens", 0))

    @property
    def total_completion_tokens(self) -> int:
        return int(getattr(self.llm, "total_completion_tokens", 0))

    @property
    def estimated_cost(self):
        return getattr(self.llm, "estimated_cost", None)

    def invoke(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        purpose: str,
        round_index: int | None = None,
    ):
        run_id = self._run_id()
        data = {
            "purpose": purpose,
            "round": round_index,
            "model": self.model,
            "message_count": len(messages),
            "messages": messages,
            "tool_definitions": tools or [],
            "request_fingerprint": request_fingerprint(
                messages,
                tools or [],
                self.workspace.root,
            ),
        }
        self.trace.emit("model_started", **data)
        notify(
            self._observer(),
            RunEvent(EventKind.MODEL_STARTED, run_id, data),
        )
        started = time.perf_counter()

        def on_delta(text: str) -> None:
            if purpose == "agent":
                notify(
                    self._observer(),
                    RunEvent(EventKind.TEXT_DELTA, run_id, {"text": text}),
                )

        try:
            response = self.llm.chat(
                messages=messages,
                tools=tools,
                on_token=on_delta if purpose == "agent" else None,
            )
        except BaseException as exc:
            failed = {
                "purpose": purpose,
                "round": round_index,
                "model": self.model,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            self.trace.emit("model_failed", **failed)
            notify(
                self._observer(),
                RunEvent(EventKind.MODEL_FAILED, run_id, failed),
            )
            raise

        finished = {
            "purpose": purpose,
            "round": round_index,
            "model": self.model,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "content": response.content,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ],
        }
        self.trace.emit("model_finished", **finished)
        notify(
            self._observer(),
            RunEvent(EventKind.MODEL_FINISHED, run_id, finished),
        )
        return response

    def chat(self, messages: list[dict], tools=None, on_token=None):
        """ContextManager adapter; all such calls are compaction calls."""
        return self.invoke(messages=messages, tools=tools, purpose="compaction")
