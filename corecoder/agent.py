"""Core agent loop.

This is the heart of CoreCoder.  The pattern is simple:

    user message -> LLM (with tools) -> tool calls? -> execute -> loop
                                      -> text reply? -> return to user

It keeps looping until the LLM responds with plain text (no tool calls),
which means it's done working and ready to report back.
"""

import concurrent.futures
import time
from dataclasses import replace

from .llm import LLM
from .tools import ToolRegistry
from .tools.base import Tool
from .tools.agent import AgentTool
from .tools.memory_search import MemorySearchTool
from .tools.memory_save import MemorySaveTool
from .prompt import system_prompt
from .context import ContextManager
from .skills import Skill
from .tools.skill import SkillTool
from .hooks import HookConfig, HookEvent
from .memory import (
    MemoryStore, extract_observations, format_memory_directory,
    format_memory_context, get_project_name,
)
from .embedding import EmbeddingService
from .trace import NullTraceSink, RunResult, TraceSink


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
        skills: list[Skill] | None = None,
        hooks: HookConfig | None = None,
        embedding: EmbeddingService | None = None,
        trace: TraceSink | None = None,
    ):
        self.llm = llm
        self.tool_registry = ToolRegistry(tools)
        self.tools = self.tool_registry.values()
        self.skills = skills if skills is not None else []
        self.hooks = hooks if hooks is not None else HookConfig()
        self.embedding = embedding or EmbeddingService(provider="none")
        self.trace = trace or NullTraceSink()
        self.active_skills: set[str] = set()
        self.messages: list[dict] = []
        self.context = ContextManager(max_tokens=max_context_tokens)
        self.max_rounds = max_rounds
        self._last_status = "idle"
        self._closed = False

        # cross-session memory
        self._project = get_project_name()
        self._memory_dir = self._load_memory_directory()
        self._system = system_prompt(self.tools, self.skills, self._memory_dir)
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

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        """Process one user message. May involve multiple LLM/tool rounds."""
        self._last_status = "running"
        self.trace.emit(
            "run_started",
            model=self.llm.model,
            user_input=user_input,
            max_rounds=self.max_rounds,
            tools=[tool.name for tool in self.tools],
        )
        self.messages.append({"role": "user", "content": user_input})

        # on-demand memory injection on first turn via hook
        self._inject_relevant_memory(user_input)

        self._maybe_compress()

        for round_index in range(self.max_rounds):
            llm_started = time.perf_counter()
            self.trace.emit(
                "llm_started",
                round=round_index,
                message_count=len(self.messages),
            )
            resp = self.llm.chat(
                messages=self._full_messages(),
                tools=self._tool_schemas(),
                on_token=on_token,
            )
            self.trace.emit(
                "llm_finished",
                round=round_index,
                duration_ms=round((time.perf_counter() - llm_started) * 1000, 2),
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                tool_calls=[tc.name for tc in resp.tool_calls],
            )

            # no tool calls -> LLM is done, return text
            if not resp.tool_calls:
                self.messages.append(resp.message)
                # ── Stop hooks ──
                self.hooks.run(HookEvent.Stop, reason="done")
                self._last_status = "completed"
                self.trace.emit(
                    "run_finished",
                    status=self._last_status,
                    changed_files=sorted(self.changed_files),
                )
                return resp.content

            # tool calls -> execute
            self.messages.append(resp.message)

            if len(resp.tool_calls) == 1:
                tc = resp.tool_calls[0]
                if on_tool:
                    on_tool(tc.name, tc.arguments)
                result = self._exec_tool(tc)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            else:
                results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                for tc, result in zip(resp.tool_calls, results):
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
        from .context import estimate_tokens

        before = estimate_tokens(self.messages)
        changed = self.context.maybe_compress(self.messages, self.llm)
        if changed:
            self.trace.emit(
                "context_compacted",
                before_tokens=before,
                after_tokens=estimate_tokens(self.messages),
                message_count=len(self.messages),
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

    def _exec_tool(self, tc) -> str:
        """Execute a single tool call, returning the result string."""
        tool = self.tool_registry.get(tc.name)
        if tool is None:
            self.trace.emit("tool_finished", tool=tc.name, status="unknown")
            return f"Error: unknown tool '{tc.name}'"

        # ── PreToolUse hooks ──
        pre = self.hooks.run(
            HookEvent.PreToolUse, tool_name=tc.name, tool_input=tc.arguments,
        )
        if pre.blocked:
            self.trace.emit(
                "policy_decision",
                tool=tc.name,
                decision="deny",
                reason=pre.message,
            )
            return f"Blocked by hook: {pre.message}"
        if pre.updated_input:
            tc = replace(tc, arguments={**tc.arguments, **pre.updated_input})

        # ── Execute ──
        started = time.perf_counter()
        self.trace.emit("tool_started", tool=tc.name, arguments=tc.arguments)
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
            tool=tc.name,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            output=output,
        )
        return output

    def _exec_tools_parallel(self, tool_calls, on_tool=None) -> list[str]:
        """Run read-only calls concurrently and side effects sequentially."""
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)

        tools = [self.tool_registry.get(tc.name) for tc in tool_calls]
        if not all(tool and tool.parallel_safe for tool in tools):
            return [self._exec_tool(tc) for tc in tool_calls]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._exec_tool, tc) for tc in tool_calls]
            return [f.result() for f in futures]

    def reset(self):
        """Clear conversation history."""
        self.messages.clear()
        self.active_skills.clear()
        self._memory_injected = False
        self._closed = False
