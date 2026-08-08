"""Acceptance coverage for the 0.4 runtime contracts."""

from pathlib import Path

import pytest

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ToolCall
from corecoder.paths import AppPaths
from corecoder.policy import ExecutionPolicy
from corecoder.runtime import WorkspaceState
from corecoder.tools import ToolRegistry
from corecoder.tools.base import Effect, Tool, ToolResult
from corecoder.trace import InMemoryTraceSink


class SequenceLLM:
    model = "test"
    estimated_cost = None

    def __init__(self, *responses):
        self.responses = list(responses)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(self, **kwargs):
        response = self.responses.pop(0)
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        return response


class UnknownTool(Tool):
    name = "unknown_effect"
    description = "intentionally undeclared"
    parameters = {"type": "object", "properties": {}}

    def execute(self):
        return ToolResult.success("should not run")


class ReadTool(Tool):
    name = "read"
    description = "read"
    parameters = {"type": "object", "properties": {}}
    effects = frozenset({Effect.READ_FS})
    parallel_safe = True

    def execute(self):
        return ToolResult.success("ok")


def make_agent(tmp_path, llm, *, tools=None, policy=None, trace=None, ephemeral=True):
    return Agent(
        llm=llm,
        tools=tools,
        policy=policy,
        trace=trace or InMemoryTraceSink(),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state"),
        ephemeral=ephemeral,
    )


def test_run_result_and_trace_are_task_local(tmp_path):
    llm = SequenceLLM(
        LLMResponse(content="one", prompt_tokens=3, completion_tokens=2),
        LLMResponse(content="two", prompt_tokens=7, completion_tokens=1),
    )
    trace = InMemoryTraceSink()
    agent = make_agent(tmp_path, llm, trace=trace)
    first, second = agent.run("first"), agent.run("second")

    assert first.run_id != second.run_id
    assert first.token.to_dict() == {"prompt": 3, "completion": 2, "total": 5}
    assert second.token.to_dict() == {"prompt": 7, "completion": 1, "total": 8}
    assert trace.events[-1]["data"]["token"]["total"] == 8


def test_workspace_is_shared_by_policy_and_tools(tmp_path):
    workspace = WorkspaceState(tmp_path)
    registry = ToolRegistry(workspace=workspace)
    target = tmp_path / "hello.txt"
    target.write_text("hello")
    result = registry.get("read_file").execute(file_path="hello.txt")

    assert result.status.value == "success"
    assert registry.get("read_file").workspace is workspace
    assert ExecutionPolicy(workspace=workspace).workspace_state is workspace


def test_undeclared_effect_is_blocked_headlessly_and_traced(tmp_path):
    trace = InMemoryTraceSink()
    llm = SequenceLLM(
        LLMResponse(
            tool_calls=[ToolCall("u1", "unknown_effect", {})],
        ),
        LLMResponse(content="blocked"),
    )
    agent = make_agent(tmp_path, llm, tools=[UnknownTool()], trace=trace)
    result = agent.run("do it")

    assert result.status == "blocked"
    finished = [event for event in trace.events if event["event"] == "tool_finished"]
    assert finished[-1]["data"]["status"] == "blocked"
    assert any(event["event"] == "approval_requested" for event in trace.events)


def test_cancel_rolls_back_incomplete_protocol(tmp_path):
    class InterruptingLLM(SequenceLLM):
        def chat(self, **kwargs):
            raise KeyboardInterrupt

    trace = InMemoryTraceSink()
    agent = make_agent(tmp_path, InterruptingLLM(), trace=trace)
    with pytest.raises(KeyboardInterrupt):
        agent.run("cancel me")

    assert agent.messages == []
    assert trace.events[-1]["data"]["status"] == "cancelled"


def test_ephemeral_agent_does_not_create_corecoder_state(tmp_path):
    agent = make_agent(
        tmp_path,
        SequenceLLM(LLMResponse(content="ok")),
        ephemeral=True,
    )
    agent.run("hello")
    agent.close()
    assert not (tmp_path / "state").exists()


def test_compaction_model_call_has_purpose_and_trace(tmp_path):
    llm = SequenceLLM(LLMResponse(content="summary"))
    trace = InMemoryTraceSink()
    agent = make_agent(tmp_path, llm, trace=trace)
    agent.messages = [
        {"role": "user", "content": f"message {index} " + "x" * 200}
        for index in range(12)
    ]
    agent._summarize = None
    agent.context._summarize_at = 1
    assert agent._maybe_compress()
    assert any(
        event["event"] == "model_started"
        and event["data"]["purpose"] == "compaction"
        for event in trace.events
    )
