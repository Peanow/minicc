"""Per-agent and per-run state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    ERROR = "error"
    EMPTY_RESPONSE = "empty_response"
    STALLED = "stalled"
    MAX_ROUNDS = "max_rounds"


@dataclass
class AgentState:
    """Mutable, instance-owned state shared by runtime-facing adapters."""

    model: str
    permission_mode: str
    workspace: str
    cwd: str
    status: RunStatus = RunStatus.IDLE
    active_skills: set[str] = field(default_factory=set)
    changed_files: set[str] = field(default_factory=set)


@dataclass
class RunState:
    """A transaction-like checkpoint for exactly one user task."""

    run_id: str
    message_checkpoint: int
    prompt_tokens_before: int
    completion_tokens_before: int
    changed_files_before: frozenset[str]
    cost_before: float | None = None
    status: RunStatus = RunStatus.RUNNING
    final_answer: str = ""
    error: str | None = None
    diffs: list[str] = field(default_factory=list)
    blocked_seen: bool = False

    def rollback_messages(self, messages: list[dict[str, Any]]) -> None:
        del messages[self.message_checkpoint :]


@dataclass(frozen=True)
class AgentStatus:
    model: str
    permission_mode: str
    workspace: str
    cwd: str
    context_tokens: int
    max_context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float | None
    changed_files: tuple[str, ...]
    active_skills: tuple[str, ...]


@dataclass(frozen=True)
class SessionState:
    messages: list[dict[str, Any]]
    model: str
    context_strategy: str
    active_skills: tuple[str, ...]
