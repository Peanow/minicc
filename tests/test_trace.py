"""Tests for instance-local tools and structured execution traces."""

import json

import pytest

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ToolCall
from corecoder.tools import ToolRegistry
from corecoder.tools.base import Effect, Tool
from corecoder.trace import (
    InMemoryTraceSink,
    JsonlTraceSink,
    redact,
    request_fingerprint,
)
from corecoder.context import create_context_strategy


class EchoTool(Tool):
    effects = frozenset({Effect.READ_FS})
    name = "echo"
    description = "Echo text."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, text: str) -> str:
        return f"echo:{text}"


class ValidationTool(Tool):
    effects = frozenset({Effect.EXECUTE})
    name = "bash"
    description = "Record a validation command without executing it."
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def execute(self, command: str) -> str:
        return f"validated:{command}"


class FakeLLM:
    model = "fake-model"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    estimated_cost = None

    def __init__(self):
        self.responses = [
            LLMResponse(
                tool_calls=[ToolCall(id="call-1", name="echo", arguments={"text": "hello"})],
                prompt_tokens=10,
                completion_tokens=2,
            ),
            LLMResponse(content="done", prompt_tokens=15, completion_tokens=3),
        ]

    def chat(self, **kwargs):
        response = self.responses.pop(0)
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        return response


class EmptyThenDoneLLM:
    model = "empty-then-done"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    estimated_cost = None

    def __init__(self, always_empty=False):
        self.always_empty = always_empty
        self.calls = 0
        self.requests = []

    def chat(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs["messages"])
        self.total_prompt_tokens += 5
        self.total_completion_tokens += 1
        if self.always_empty or self.calls == 1:
            return LLMResponse(content="", prompt_tokens=5, completion_tokens=1)
        return LLMResponse(content="done", prompt_tokens=5, completion_tokens=1)


class StagnantLLM:
    model = "stagnant"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    estimated_cost = None

    def __init__(self, finish_after=None):
        self.finish_after = finish_after
        self.calls = 0
        self.requests = []

    def chat(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs["messages"])
        if self.finish_after is not None and self.calls > self.finish_after:
            return LLMResponse(content="done")
        return LLMResponse(tool_calls=[ToolCall(
            id=f"read-{self.calls}",
            name="echo",
            arguments={"text": "still inspecting"},
        )])


def test_tool_registry_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate tool name"):
        ToolRegistry([EchoTool(), EchoTool()])


def test_agent_executes_its_private_tool_registry():
    trace = InMemoryTraceSink()
    agent = Agent(llm=FakeLLM(), tools=[EchoTool()], trace=trace)

    result = agent.run("use echo")

    assert result.status == "completed"
    assert result.final_answer == "done"
    assert result.prompt_tokens == 25
    run_started = trace.events[0]
    assert run_started["data"]["context_strategy"] == "hybrid"
    assert run_started["data"]["token_counter"] == "approx"
    assert run_started["data"]["permission_mode"] == "workspace-write"
    assert run_started["data"]["workspace"]
    llm_started = next(event for event in trace.events if event["event"] == "model_started")
    assert len(llm_started["data"]["request_fingerprint"]) == 64
    events = [event["event"] for event in trace.events]
    assert events == [
        "run_started",
        "model_started",
        "model_finished",
        "tool_requested",
        "policy_decision",
        "tool_started",
        "tool_finished",
        "tool_result",
        "model_started",
        "model_finished",
        "run_finished",
    ]
    tool_event = next(e for e in trace.events if e["event"] == "tool_finished")
    assert tool_event["data"]["content"] == "echo:hello"
    policy_event = next(e for e in trace.events if e["event"] == "policy_decision")
    assert policy_event["data"]["risk"] == "read-only"


def test_workspace_validation_allowance_is_visible_in_trace():
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=FakeLLM(),
        tools=[ValidationTool()],
        trace=trace,
        policy=__import__("corecoder.policy", fromlist=["ExecutionPolicy"]).ExecutionPolicy("full-access"),
    )

    output = agent._exec_tool(ToolCall(
        id="validation-1",
        name="bash",
        arguments={"command": "python -m pytest -q"},
    ))

    assert output.content == "validated:python -m pytest -q"
    policy_event = next(
        event for event in trace.events if event["event"] == "policy_decision"
    )
    assert policy_event["data"]["decision"] == "allow"
    assert policy_event["data"]["risk"] == "workspace-validation"


def test_approval_decision_is_recorded_without_arguments(tmp_path):
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=FakeLLM(),
        tools=[ValidationTool()],
        trace=trace,
        workspace=tmp_path,
        policy=__import__("corecoder.policy", fromlist=["ExecutionPolicy"]).ExecutionPolicy(
            "workspace-write",
            workspace=tmp_path,
            approval_callback=lambda _request: "once",
        ),
    )

    result = agent._exec_tool(ToolCall(
        id="approval-1",
        name="bash",
        arguments={"command": "make API_KEY=top-secret"},
    ))

    assert result.status.value == "success"
    event = next(event for event in trace.events if event["event"] == "approval_decided")
    assert event["data"]["outcome"] == "once"
    assert event["data"]["decision"] == "allow"
    assert event["data"]["tool_call_id"] == "approval-1"
    assert "arguments" not in event["data"]
    assert "top-secret" not in json.dumps(event)


def test_agent_retries_empty_model_response_with_trace_event():
    llm = EmptyThenDoneLLM()
    trace = InMemoryTraceSink()
    agent = Agent(llm=llm, tools=[], trace=trace)

    result = agent.run("finish the task")

    assert result.status == "completed"
    assert result.final_answer == "done"
    assert llm.calls == 2
    assert "[Runtime recovery]" in llm.requests[1][-1]["content"]
    retry = next(
        event for event in trace.events
        if event["event"] == "empty_response_retry"
    )
    assert retry["data"] == {"round": 0, "attempt": 1, "max_retries": 2}


def test_agent_marks_exhausted_empty_responses_as_failure():
    llm = EmptyThenDoneLLM(always_empty=True)
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=llm,
        tools=[],
        trace=trace,
        max_empty_response_retries=1,
    )

    result = agent.run("finish the task")

    assert result.status == "empty_response"
    assert llm.calls == 2
    assert any(
        event["event"] == "empty_response_exhausted"
        for event in trace.events
    )
    finished = next(
        event for event in trace.events if event["event"] == "run_finished"
    )
    assert finished["data"]["status"] == "empty_response"


def test_agent_recovers_from_read_only_stagnation_with_trace_event():
    llm = StagnantLLM(finish_after=2)
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=llm,
        tools=[EchoTool()],
        trace=trace,
        max_stagnation_rounds=2,
    )

    result = agent.run("make a focused change")

    assert result.status == "completed"
    assert "[Runtime recovery]" in llm.requests[2][-1]["content"]
    recovery = next(
        event for event in trace.events
        if event["event"] == "stagnation_recovery"
    )
    assert recovery["data"]["stagnant_rounds"] == 2


def test_agent_stops_after_stagnation_recovery_is_exhausted():
    llm = StagnantLLM()
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=llm,
        tools=[EchoTool()],
        trace=trace,
        max_rounds=10,
        max_stagnation_rounds=2,
        max_stagnation_retries=1,
    )

    result = agent.run("make a focused change")

    assert result.status == "stalled"
    assert llm.calls == 4
    exhausted = next(
        event for event in trace.events
        if event["event"] == "stagnation_exhausted"
    )
    assert exhausted["data"]["attempts"] == 1
    finished = next(
        event for event in trace.events if event["event"] == "run_finished"
    )
    assert finished["data"]["status"] == "stalled"


def test_jsonl_trace_is_append_only_and_redacted(tmp_path):
    path = tmp_path / "run.jsonl"
    sink = JsonlTraceSink(path, run_id="test-run")
    sink.emit(
        "llm_started",
        authorization="Bearer secret-token-value",
        api_key="sk-1234567890abcdefghijkl",
    )
    sink.close()

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["run_id"] == "test-run"
    serialized = json.dumps(records[0])
    assert "secret-token-value" not in serialized
    assert "sk-1234567890abcdefghijkl" not in serialized
    assert "REDACTED" in serialized


def test_request_fingerprint_is_stable_across_workspace_paths(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    messages_first = [{"role": "user", "content": f"Read {first}/app.py"}]
    messages_second = [{"role": "user", "content": f"Read {second}/app.py"}]

    assert request_fingerprint(messages_first, [], first) == request_fingerprint(
        messages_second,
        [],
        second,
    )


def test_redact_nested_values():
    result = redact({
        "items": ["token=abc123", "safe"],
        "api_key": "provider-specific-format",
        "prompt_tokens": 42,
    })
    assert result == {
        "items": ["token=[REDACTED]", "safe"],
        "api_key": "[REDACTED]",
        "prompt_tokens": 42,
    }


def test_otel_attribute_serialization_has_a_total_bound():
    from corecoder.trace import _attribute_value

    value = {str(index): "x" * 1000 for index in range(100)}
    serialized = _attribute_value(value)
    assert isinstance(serialized, str)
    assert len(serialized) < 12_000
    assert "trace truncated" in serialized


def test_context_compaction_trace_records_strategy_and_counter():
    class CharacterCounter:
        name = "characters"

        def count_text(self, text):
            return len(text)

        def count_messages(self, messages):
            return sum(len(str(message.get("content") or "")) for message in messages)

    trace = InMemoryTraceSink()
    context = create_context_strategy(
        "truncate",
        max_tokens=3000,
        token_counter=CharacterCounter(),
    )
    agent = Agent(
        llm=FakeLLM(),
        tools=[EchoTool()],
        trace=trace,
        context_strategy=context,
    )
    agent.messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "old",
                "type": "function",
                "function": {"name": "echo", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "old",
            "content": "\n".join("x" * 100 for _ in range(30)),
        },
    ]

    assert agent._maybe_compress()
    event = next(item for item in trace.events if item["event"] == "context_compacted")
    assert event["data"]["strategy"] == "truncate"
    assert event["data"]["token_counter"] == "characters"
    assert event["data"]["fixed_tokens"] > 0
    assert event["data"]["before_tokens"] > event["data"]["after_tokens"]
    assert "tool_snip" in event["data"]["operations"]
    assert event["data"]["after_tokens"] == agent.context_tokens()
    assert event["data"]["protocol_valid"]
