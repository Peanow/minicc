"""Core agent loop.

This is the heart of CoreCoder.  The pattern is simple:

    user message -> LLM (with tools) -> tool calls? -> execute -> loop
                                      -> text reply? -> return to user

It keeps looping until the LLM responds with plain text (no tool calls),
which means it's done working and ready to report back.
"""

import concurrent.futures
import json
import time
from dataclasses import replace

from .llm import LLM
from .tools import ToolRegistry
from .tools.base import Tool
from .tools.agent import AgentTool
from .tools.memory_search import MemorySearchTool
from .tools.memory_save import MemorySaveTool
from .prompt import system_prompt
from .context import (
    ContextManager,
    create_context_strategy,
    tool_protocol_valid,
)
from .tokenizer import TokenCounter
from .skills import Skill
from .tools.skill import SkillTool
from .hooks import HookConfig, HookEvent
from .memory import (
    MemoryStore, extract_observations, format_memory_directory,
    format_memory_context, get_project_name,
)
from .embedding import EmbeddingService
from .trace import NullTraceSink, RunResult, TraceSink, request_fingerprint
from .instructions import format_project_instructions, load_project_instructions
from .policy import Decision, ExecutionPolicy


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
        max_empty_response_retries: int = 2,
        skills: list[Skill] | None = None,
        hooks: HookConfig | None = None,
        embedding: EmbeddingService | None = None,
        trace: TraceSink | None = None,
        instruction_sources=None,
        policy: ExecutionPolicy | None = None,
        context_strategy: str | ContextManager = "hybrid",
        token_counter: TokenCounter | None = None,
    ):
        self.llm = llm
        self.tool_registry = ToolRegistry(tools)
        self.tools = self.tool_registry.values()
        self.skills = skills if skills is not None else []
        self.hooks = hooks if hooks is not None else HookConfig()
        self.embedding = embedding or EmbeddingService(provider="none")
        self.trace = trace or NullTraceSink()
        self.policy = policy or ExecutionPolicy()
        self.active_skills: set[str] = set()
        self.messages: list[dict] = []
        self.context = (
            context_strategy
            if isinstance(context_strategy, ContextManager)
            else create_context_strategy(
                context_strategy,
                max_tokens=max_context_tokens,
                token_counter=token_counter,
            )
        )
        self.max_rounds = max_rounds
        if max_empty_response_retries < 0:
            raise ValueError("max_empty_response_retries must be non-negative")
        self.max_empty_response_retries = max_empty_response_retries
        self._last_status = "idle"
        self._closed = False

        # cross-session memory
        self._project = get_project_name()
        self.instruction_sources = (
            list(instruction_sources)
            if instruction_sources is not None
            else load_project_instructions()
        )
        self._memory_dir = self._load_memory_directory()
        self._system = ""
        self.refresh_system_prompt()
        self._memory_injected = False

        # ── Register hook callbacks for memory lifecycle ──
        # MemorySave: triggered at session end → extract & persist observations
        # MemoryInject: triggered at session start → inject relevant memories
        self.hooks.register_callback(
            HookEvent.MemorySave, self._on_memory_save, name="memory_save",
        )
        self.hooks.register_callback(
            HookEvent.MemoryInject, self._on_memory_inject, name="memory_inject",
        )

        # wire up sub-agent, skill, and memory capabilities
        for t in self.tools:
            if isinstance(t, AgentTool):
                t._parent_agent = self
            if isinstance(t, SkillTool):
                t._agent = self
            if isinstance(t, (MemorySearchTool, MemorySaveTool)):
                t._agent = self

    @property
    def changed_files(self) -> set[str]:
        """Files changed by tools owned by this agent."""
        return self.tool_registry.changed_files

    def refresh_system_prompt(self):
        self._system = system_prompt(
            self.tools,
            self.skills,
            self._memory_dir,
            format_project_instructions(self.instruction_sources),
        )

    def _full_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system}] + self.messages

    # ---- Hook callbacks for memory ----

    def _on_memory_save(self, **kwargs) -> int:
        """Hook callback: extract observations from conversation and persist.

        Triggered by MemorySave hook at session end. SQLite stores both
        full observations and optional embedding vectors.
        """
        if not self.messages:
            return 0
        try:
            observations = extract_observations(
                self.messages, project=self._project,
            )
            if not observations:
                return 0

            # generate embeddings via local model
            texts = [f"{o.title}: {o.content}" for o in observations]
            embeddings = (
                self.embedding.embed_batch(texts)
                if self.embedding.is_available()
                else None
            )

            # single-store persistence: content and optional vectors in SQLite
            store = MemoryStore(embedding_dims=self.embedding.dims)
            try:
                results = store.save_many(observations, embeddings=embeddings)
            finally:
                store.close()
            return sum(1 for r in results if r is not None)
        except Exception:
            return 0

    def _on_memory_inject(self, **kwargs) -> str:
        """Hook callback: inject relevant memories into conversation.

        Triggered by MemoryInject hook at session start. Performs hybrid
        keyword/vector search in the project-scoped SQLite store.
        """
        user_input = kwargs.get("user_input", "")
        if not user_input:
            return ""

        query_emb = (
            self.embedding.embed(user_input)
            if self.embedding.is_available()
            else None
        )

        try:
            store = MemoryStore(embedding_dims=self.embedding.dims)
            try:
                if query_emb:
                    relevant = store.hybrid_search(
                        self._project, user_input, query_emb, limit=5,
                    )
                else:
                    relevant = store.search(self._project, user_input, limit=5)
            finally:
                store.close()
        except Exception:
            return ""

        if relevant:
            return format_memory_context(relevant)
        return ""

    def _load_memory_directory(self) -> str:
        """Load lightweight memory titles for the system prompt."""
        try:
            store = MemoryStore(embedding_dims=self.embedding.dims)
            try:
                titles = store.get_recent_titles(self._project, limit=20)
            finally:
                store.close()
            return format_memory_directory(titles) if titles else ""
        except Exception:
            return ""

    def _inject_relevant_memory(self, user_input: str):
        """On first user turn, fire MemoryInject hook to inject relevant memories."""
        if self._memory_injected:
            return
        self._memory_injected = True

        result = self.hooks.run(
            HookEvent.MemoryInject, user_input=user_input,
        )
        context = result.data
        if context and isinstance(context, str) and context.strip():
            self.messages.insert(-1, {
                "role": "user",
                "content": context,
            })
            self.messages.append({
                "role": "assistant",
                "content": "Noted. I'll consider these memories from previous sessions.",
            })

    def _tool_schemas(self) -> list[dict]:
        return self.tool_registry.schemas()

    def _fixed_context_tokens(self) -> int:
        """Tokens sent on every request outside the mutable message history."""
        return (
            self.context.token_counter.count_messages([{
                "role": "system",
                "content": self._system,
            }])
            + self.context.token_counter.count_text(
                json.dumps(
                    self._tool_schemas(),
                    ensure_ascii=False,
                    default=str,
                )
            )
        )

    def context_tokens(self) -> int:
        """Estimate the complete request context using the active counter."""
        return (
            self._fixed_context_tokens()
            + self.context.count_messages(self.messages)
        )

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        """Process one user task inside a complete, independently identified run."""
        self.trace.begin_run()
        try:
            answer = self._chat_impl(user_input, on_token=on_token, on_tool=on_tool)
        except KeyboardInterrupt:
            self._last_status = "cancelled"
            self.trace.emit(
                "run_finished",
                status=self._last_status,
                changed_files=sorted(self.changed_files),
                error_type="KeyboardInterrupt",
            )
            self.trace.end_run(self._last_status)
            raise
        except Exception as exc:
            self._last_status = "error"
            self.trace.emit(
                "run_finished",
                status=self._last_status,
                changed_files=sorted(self.changed_files),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self.trace.end_run(self._last_status)
            raise
        self.trace.end_run(self._last_status)
        return answer

    def _chat_impl(self, user_input: str, on_token=None, on_tool=None) -> str:
        """Execute the agent loop after the trace lifecycle has been opened."""
        self._last_status = "running"
        self.trace.emit(
            "run_started",
            model=self.llm.model,
            user_input=user_input,
            max_rounds=self.max_rounds,
            max_empty_response_retries=self.max_empty_response_retries,
            tools=[tool.name for tool in self.tools],
            instruction_sources=[{
                "path": str(source.path),
                "loaded_bytes": source.loaded_bytes,
                "source_bytes": source.source_bytes,
                "truncated": source.truncated,
            } for source in self.instruction_sources],
            context_strategy=self.context.strategy_name,
            token_counter=self.context.token_counter.name,
            max_context_tokens=self.context.max_tokens,
            workspace=str(self.policy.workspace),
            permission_mode=self.policy.mode.value,
        )
        self.messages.append({"role": "user", "content": user_input})

        # on-demand memory injection on first turn via hook
        self._inject_relevant_memory(user_input)

        self._maybe_compress()

        empty_response_retries = 0
        for round_index in range(self.max_rounds):
            llm_started = time.perf_counter()
            full_messages = self._full_messages()
            tool_schemas = self._tool_schemas()
            self.trace.emit(
                "llm_started",
                round=round_index,
                model=self.llm.model,
                message_count=len(self.messages),
                messages=full_messages,
                tool_definitions=tool_schemas,
                request_fingerprint=request_fingerprint(
                    full_messages,
                    tool_schemas,
                    self.policy.workspace,
                ),
            )
            resp = self.llm.chat(
                messages=full_messages,
                tools=tool_schemas,
                on_token=on_token,
            )
            self.trace.emit(
                "llm_finished",
                round=round_index,
                duration_ms=round((time.perf_counter() - llm_started) * 1000, 2),
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                content=resp.content,
                tool_calls=[{
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                } for tc in resp.tool_calls],
            )

            # no tool calls -> LLM is done, return text
            if not resp.tool_calls:
                if not (resp.content or "").strip():
                    if empty_response_retries < self.max_empty_response_retries:
                        empty_response_retries += 1
                        recovery_message = (
                            "[Runtime recovery] Your previous response was empty. "
                            "Continue the task: inspect or edit with tools if work "
                            "remains, otherwise return a concise final answer."
                        )
                        self.messages.append({
                            "role": "user",
                            "content": recovery_message,
                        })
                        self.trace.emit(
                            "empty_response_retry",
                            round=round_index,
                            attempt=empty_response_retries,
                            max_retries=self.max_empty_response_retries,
                        )
                        self._maybe_compress()
                        continue

                    answer = (
                        "(model returned empty responses and exhausted runtime "
                        "recovery retries)"
                    )
                    self.hooks.run(HookEvent.Stop, reason="empty_response")
                    self._last_status = "empty_response"
                    self.trace.emit(
                        "empty_response_exhausted",
                        round=round_index,
                        attempts=empty_response_retries,
                    )
                    self.trace.emit(
                        "run_finished",
                        status=self._last_status,
                        changed_files=sorted(self.changed_files),
                        final_answer=answer,
                    )
                    return answer

                self.messages.append(resp.message)
                # ── Stop hooks ──
                self.hooks.run(HookEvent.Stop, reason="done")
                self._last_status = "completed"
                self.trace.emit(
                    "run_finished",
                    status=self._last_status,
                    changed_files=sorted(self.changed_files),
                    final_answer=resp.content,
                )
                return resp.content

            # tool calls -> execute
            empty_response_retries = 0
            self.messages.append(resp.message)

            if len(resp.tool_calls) == 1:
                tc = resp.tool_calls[0]
                if on_tool:
                    on_tool(tc.name, tc.arguments)
                result = self._exec_tool(tc, round_index=round_index)
                self.trace.emit(
                    "tool_result",
                    tool_call_id=tc.id,
                    tool=tc.name,
                    round=round_index,
                    content=result,
                )
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            else:
                results = self._exec_tools_parallel(
                    resp.tool_calls,
                    on_tool,
                    round_index=round_index,
                )
                for tc, result in zip(resp.tool_calls, results):
                    self.trace.emit(
                        "tool_result",
                        tool_call_id=tc.id,
                        tool=tc.name,
                        round=round_index,
                        content=result,
                    )
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            self._maybe_compress()

        self.hooks.run(HookEvent.Stop, reason="max_rounds")
        self._last_status = "max_rounds"
        self.trace.emit(
            "run_finished",
            status=self._last_status,
            changed_files=sorted(self.changed_files),
            final_answer="(reached maximum tool-call rounds)",
        )
        return "(reached maximum tool-call rounds)"

    def run(self, user_input: str, on_token=None, on_tool=None) -> RunResult:
        """Run one task and return a structured result for automation."""
        answer = self.chat(user_input, on_token=on_token, on_tool=on_tool)
        trace_path = getattr(self.trace, "path", None)
        return RunResult(
            status=self._last_status,
            final_answer=answer,
            changed_files=sorted(self.changed_files),
            prompt_tokens=self.llm.total_prompt_tokens,
            completion_tokens=self.llm.total_completion_tokens,
            estimated_cost=self.llm.estimated_cost,
            trace_path=str(trace_path) if trace_path else None,
        )

    def _maybe_compress(self):
        fixed_tokens = self._fixed_context_tokens()
        before = self.context_tokens()
        changed = self.context.maybe_compress(
            self.messages,
            self.llm,
            fixed_tokens=fixed_tokens,
        )
        if changed:
            self.trace.emit(
                "context_compacted",
                before_tokens=before,
                after_tokens=self.context_tokens(),
                fixed_tokens=fixed_tokens,
                message_count=len(self.messages),
                strategy=self.context.strategy_name,
                operations=self.context.last_operations,
                token_counter=self.context.token_counter.name,
                protocol_valid=tool_protocol_valid(self.messages),
            )
        return changed

    def close(self):
        """Finalize the session and persist memory once."""
        if self._closed:
            return
        self._closed = True
        result = self.hooks.run(HookEvent.MemorySave)
        self.trace.emit(
            "memory_written",
            count=result.data if isinstance(result.data, int) else 0,
        )

    def _exec_tool(self, tc, round_index: int | None = None) -> str:
        """Execute a single tool call, returning the result string."""
        tool = self.tool_registry.get(tc.name)
        if tool is None:
            self.trace.emit(
                "tool_rejected",
                tool_call_id=tc.id,
                tool=tc.name,
                round=round_index,
                reason="unknown tool",
            )
            return f"Error: unknown tool '{tc.name}'"

        # ── PreToolUse hooks ──
        pre = self.hooks.run(
            HookEvent.PreToolUse, tool_name=tc.name, tool_input=tc.arguments,
        )
        if pre.blocked:
            self.trace.emit(
                "policy_decision",
                tool_call_id=tc.id,
                tool=tc.name,
                round=round_index,
                decision="deny",
                reason=pre.message,
            )
            return f"Blocked by hook: {pre.message}"
        if pre.updated_input:
            tc = replace(tc, arguments={**tc.arguments, **pre.updated_input})

        policy = self.policy.authorize(tc.name, tc.arguments)
        self.trace.emit(
            "policy_decision",
            tool_call_id=tc.id,
            tool=tc.name,
            round=round_index,
            decision=policy.decision.value,
            reason=policy.reason,
            risk=policy.risk.value,
        )
        if policy.decision != Decision.ALLOW:
            return f"Blocked by policy: {policy.reason}"

        # ── Execute ──
        started = time.perf_counter()
        self.trace.emit(
            "tool_started",
            tool_call_id=tc.id,
            tool=tc.name,
            round=round_index,
            arguments=tc.arguments,
        )
        try:
            output = tool.execute(**tc.arguments)
        except TypeError as e:
            output = f"Error: bad arguments for {tc.name}: {e}"
        except Exception as e:
            output = f"Error executing {tc.name}: {e}"

        # ── PostToolUse hooks ──
        post = self.hooks.run(
            HookEvent.PostToolUse,
            tool_name=tc.name, tool_input=tc.arguments, tool_output=output,
        )
        if post.updated_output is not None:
            output = post.updated_output

        self.trace.emit(
            "tool_finished",
            tool_call_id=tc.id,
            tool=tc.name,
            round=round_index,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            output=output,
        )
        return output

    def _exec_tools_parallel(
        self,
        tool_calls,
        on_tool=None,
        round_index: int | None = None,
    ) -> list[str]:
        """Run read-only calls concurrently and side effects sequentially."""
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)

        tools = [self.tool_registry.get(tc.name) for tc in tool_calls]
        if not all(tool and tool.parallel_safe for tool in tools):
            return [self._exec_tool(tc, round_index=round_index) for tc in tool_calls]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(self._exec_tool, tc, round_index)
                for tc in tool_calls
            ]
            return [f.result() for f in futures]

    def reset(self):
        """Clear conversation history."""
        self.messages.clear()
        self.active_skills.clear()
        self._memory_injected = False
        self._closed = False
