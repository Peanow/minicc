"""Composition and compatibility adapters for CLI-facing runtime APIs."""

from __future__ import annotations

import inspect
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from corecoder.agent import Agent
from corecoder.config import Config
from corecoder.context import create_context_strategy
from corecoder.embedding import EmbeddingService
from corecoder.hooks import HookEvent, load_hooks
from corecoder.llm import LLM, LiteLLM
from corecoder.observability import ObservabilityConfig, PhoenixManager
from corecoder.paths import AppPaths
from corecoder.policy import ExecutionPolicy
from corecoder.session import SessionError, SessionRecord, SessionStore
from corecoder.skills import discover_skills, find_skill_by_name, format_skill_invocation
from corecoder.tokenizer import create_token_counter
from corecoder.trace import CompositeTraceSink, JsonlTraceSink, OpenTelemetryTraceSink, TraceSink


Observer = Callable[[Any], None]


class ConfigurationError(RuntimeError):
    """The runtime could not be assembled from user configuration."""


def apply_runtime_options(config: Config, args: Any) -> Config:
    for attr, config_attr in (
        ("model", "model"),
        ("base_url", "base_url"),
        ("permission_mode", "permission_mode"),
        ("context_strategy", "context_strategy"),
        ("tokenizer", "tokenizer_provider"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            setattr(config, config_attr, value)
    return config


def _filter_kwargs(callable_: Any, values: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(callable_)
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return values
    return {name: value for name, value in values.items() if name in signature.parameters}


class TraceObserverBridge(TraceSink):
    """Expose v1 trace events through the v2 observer protocol."""

    _RENAMES = {
        "llm_started": "model_started",
        "llm_finished": "model_finished",
        "llm_failed": "model_failed",
    }

    def __init__(self, observer: Observer):
        self.observer = observer
        self.run_id = ""
        self.session_id = ""

    def begin_run(self, run_id: str | None = None) -> str:
        self.run_id = run_id or uuid.uuid4().hex
        return self.run_id

    def emit(self, event: str, **data: Any) -> None:
        if event in {"tool_result", "run_finished"}:
            # v1 emits a richer tool_finished immediately before tool_result.
            # run_finished is reconstructed from RunResult so its v2 payload
            # includes task-local token/cost/error accounting.
            return
        self.observer({
            "kind": self._RENAMES.get(event, event),
            "run_id": self.run_id,
            "timestamp": time.time(),
            "data": data,
        })


class SessionAdapter:
    """The only CLI dependency on the concrete session persistence API."""

    def __init__(self, app_paths: AppPaths, workspace: Path):
        self.store = SessionStore(app_paths, workspace)
        self.session_id: str | None = None

    def list(self) -> list[SessionRecord]:
        return self.store.list(limit=20)

    def load(self, session_id: str) -> SessionRecord:
        record = self.store.load(session_id)
        if record is None:
            raise SessionError(f"Session {session_id!r} was not found in this project.")
        return record

    def latest(self) -> SessionRecord:
        record = self.store.latest()
        if record is None:
            raise SessionError("No saved session exists for this project.")
        return record

    def delete(self, session_id: str) -> bool:
        return self.store.delete(session_id)

    def restore(self, agent: Agent, record: SessionRecord) -> None:
        restore = getattr(agent, "restore_session", None)
        if callable(restore):
            restore(record)
        else:
            agent.messages = [dict(message) for message in record.messages]
            switch_agent_model(agent, record.model)
            if hasattr(agent, "active_skills"):
                agent.active_skills.clear()
            prompts = getattr(agent, "_active_skill_prompts", None)
            if isinstance(prompts, dict):
                prompts.clear()
            for skill_name in record.active_skills:
                try:
                    activate_agent_skill(agent, skill_name)
                except ValueError:
                    # A session remains recoverable if a project skill was
                    # removed after the checkpoint was created.
                    continue
        self.session_id = record.id

    def checkpoint(
        self,
        agent: Agent,
        config: Config,
        *,
        status: str = "completed",
    ) -> SessionRecord:
        export = getattr(agent, "session_state", None)
        if callable(export):
            state = export()
            messages = state.messages
            model = state.model
            active_skills = list(state.active_skills)
        else:
            messages = list(getattr(agent, "messages", []))
            model = str(getattr(getattr(agent, "llm", None), "model", config.model))
            active_skills = sorted(getattr(agent, "active_skills", set()))
        record = self.store.save(
            messages,
            model,
            self.session_id,
            context_strategy=config.context_strategy,
            active_skills=active_skills,
            last_run_status=status,
        )
        self.session_id = record.id
        return record


@dataclass
class RuntimeBundle:
    agent: Agent
    config: Config
    app_paths: AppPaths
    workspace: Path
    sessions: SessionAdapter
    manager: PhoenixManager
    ephemeral: bool = False

    @property
    def history_file(self) -> Path | None:
        if self.ephemeral:
            return None
        return self.app_paths.for_project(self.workspace).history_file

    def close(self) -> None:
        # Agent owns its memory boundary; an ephemeral Agent has a disabled
        # MemoryService, so close remains safe while releasing all resources.
        self.agent.close()
        trace = getattr(self.agent, "trace", None)
        if trace is not None:
            trace.close()


def build_runtime(
    args: Any,
    *,
    workspace: str | Path | None = None,
    approval_callback: Callable[..., Any] | None = None,
    ephemeral: bool | None = None,
) -> RuntimeBundle:
    workspace_path = Path(workspace or Path.cwd()).expanduser().resolve()
    config = apply_runtime_options(Config.from_env(), args)

    # Configuration is loaded before the rest of the composition root so the
    # startup decision is observable even when validation fails.  The payload
    # contains only source labels, paths, and booleans; Config never exposes
    # the key value through this event.
    trace_sinks = []
    trace_path = getattr(args, "trace", None)
    if trace_path:
        trace_sinks.append(JsonlTraceSink(trace_path))
    trace = CompositeTraceSink(trace_sinks)
    if trace_path:
        trace.path = Path(trace_path).expanduser().resolve()
    trace.emit("config_loaded", **config.trace_metadata())

    if not config.api_key:
        trace.close()
        raise ConfigurationError(
            "No API key found. Set OPENAI_API_KEY, DEEPSEEK_API_KEY, "
            "or CORECODER_API_KEY."
        )

    if os.getenv("CORECODER_SANITIZE_TOOL_ENV") == "1":
        for key in (
            "CORECODER_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
            "CORECODER_EVAL_COMPARISON_API_KEY",
        ):
            os.environ.pop(key, None)
        os.environ.pop("CORECODER_SANITIZE_TOOL_ENV", None)

    llm_cls = LiteLLM if config.provider == "litellm" else LLM
    llm = llm_cls(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    embedding = EmbeddingService(
        provider=config.embedding_provider,
        model=config.embedding_model,
        dims=config.embedding_dims,
        api_key=config.api_key,
        base_url=config.base_url,
    )
    try:
        observability = ObservabilityConfig.from_env()
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    manager = PhoenixManager(observability)
    if getattr(args, "observe", False):
        manager.up()
    if getattr(args, "observe", False) or observability.backend == "otel":
        trace.add_sink(manager.create_trace_sink(trace.session_id))

    app_paths = AppPaths()
    policy = ExecutionPolicy(
        mode=config.permission_mode,
        workspace=workspace_path,
        approval_callback=approval_callback,
    )
    context = create_context_strategy(
        config.context_strategy,
        max_tokens=config.max_context_tokens,
        token_counter=create_token_counter(config.tokenizer_provider, config.model),
    )
    is_ephemeral = bool(ephemeral if ephemeral is not None else getattr(args, "ephemeral", False))
    agent_values = {
        "llm": llm,
        "workspace": workspace_path,
        "app_paths": app_paths,
        "ephemeral": is_ephemeral,
        "max_context_tokens": config.max_context_tokens,
        "skills": discover_skills(cwd=workspace_path),
        "hooks": load_hooks(),
        "embedding": embedding,
        "trace": trace,
        "policy": policy,
        "context_strategy": context,
    }
    try:
        agent = Agent(**_filter_kwargs(Agent, agent_values))
    except (TypeError, ValueError) as exc:
        trace.close()
        raise ConfigurationError(f"Unable to initialize Agent: {exc}") from exc
    return RuntimeBundle(
        agent=agent,
        config=config,
        app_paths=app_paths,
        workspace=workspace_path,
        sessions=SessionAdapter(app_paths, workspace_path),
        manager=manager,
        ephemeral=is_ephemeral,
    )


def start_agent_session(agent: Agent) -> str | None:
    hooks = getattr(agent, "hooks", None)
    if hooks is None:
        return None
    result = hooks.run(HookEvent.SessionStart)
    return getattr(result, "message", None)


def run_agent(agent: Agent, prompt: str, observer: Observer) -> Any:
    """Call the public v2 observer API."""
    signature = inspect.signature(agent.run)
    if "observer" in signature.parameters:
        pending_finish: list[Any] = []

        def forward(event: Any) -> None:
            kind = getattr(event, "kind", None)
            value = getattr(kind, "value", kind)
            if str(value).lower() == "run_finished":
                pending_finish[:] = [event]
            else:
                observer(event)

        try:
            result = agent.run(prompt, observer=forward)
        except BaseException:
            if pending_finish:
                observer(pending_finish[-1])
            raise
        if pending_finish:
            observer(pending_finish[-1])
        else:
            payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            observer({
                "kind": "run_finished",
                "run_id": str(payload.get("run_id", "")),
                "timestamp": time.time(),
                "data": payload,
            })
        return result

    raise ConfigurationError("Agent does not expose the required observer API")


def status_from_agent(agent: Agent) -> dict[str, Any]:
    status = getattr(agent, "status", None)
    if callable(status):
        value = status()
        if isinstance(value, dict):
            result = dict(value)
        elif hasattr(value, "to_dict"):
            result = dict(value.to_dict())
        elif hasattr(value, "__dict__"):
            result = dict(vars(value))
        else:
            result = {}
        if result:
            prompt = int(result.get("prompt_tokens", 0) or 0)
            completion = int(result.get("completion_tokens", 0) or 0)
            result.setdefault("total_tokens", prompt + completion)
            result.setdefault("cost", getattr(getattr(agent, "llm", None), "estimated_cost", None))
            return result
    llm = getattr(agent, "llm", None)
    prompt = int(getattr(llm, "total_prompt_tokens", 0) or 0)
    completion = int(getattr(llm, "total_completion_tokens", 0) or 0)
    return {
        "model": getattr(llm, "model", "unknown"),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost": getattr(llm, "estimated_cost", None),
        "changed_files": sorted(getattr(agent, "changed_files", set())),
        "active_skills": sorted(getattr(agent, "active_skills", set())),
    }


def clear_agent(agent: Agent) -> None:
    clear = getattr(agent, "clear", None)
    if callable(clear):
        clear()
    else:
        agent.reset()


def compact_agent(agent: Agent) -> Any:
    compact = getattr(agent, "compact", None)
    if callable(compact):
        return compact()
    return agent._maybe_compress()


def switch_agent_model(agent: Agent, model: str) -> None:
    switch = getattr(agent, "switch_model", None)
    if callable(switch):
        switch(model)
    else:
        agent.llm.model = model


def activate_agent_skill(agent: Agent, name: str) -> Any:
    activate = getattr(agent, "activate_skill", None)
    if callable(activate):
        return activate(name)
    skill = find_skill_by_name(getattr(agent, "skills", []), name)
    if skill is None:
        raise ValueError(f"Skill {name!r} was not found.")
    agent.active_skills.add(skill.name)
    agent.messages.append({"role": "user", "content": format_skill_invocation(skill)})
    refresh = getattr(agent, "refresh_system_prompt", None)
    if callable(refresh):
        refresh()
    return skill


def attach_observability(bundle: RuntimeBundle, *, open_browser: bool = True) -> str:
    manager = bundle.manager
    opened = manager.open() if open_browser else True
    if not open_browser:
        manager.up()
    trace = getattr(bundle.agent, "trace", None)
    if not isinstance(trace, CompositeTraceSink):
        raise ConfigurationError("The active Agent trace sink cannot be extended.")
    if not any(isinstance(sink, OpenTelemetryTraceSink) for sink in trace.sinks):
        trace.add_sink(manager.create_trace_sink(trace.session_id))
    suffix = "" if opened else " (browser could not be opened)"
    return manager.config.ui_url + suffix
