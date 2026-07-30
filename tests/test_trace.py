"""Tests for instance-local tools and structured execution traces."""

import json

import pytest

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ToolCall
from corecoder.tools import ToolRegistry
from corecoder.tools.base import Tool
from corecoder.trace import (
    InMemoryTraceSink,
    JsonlTraceSink,
    redact,
    request_fingerprint,
)
from corecoder.context import create_context_strategy


class EchoTool(Tool):
    name = "echo"
    description = "Echo text."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, text: str) -> str:
        return f"echo:{text}"


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
    llm_started = next(event for event in trace.events if event["event"] == "llm_started")
    assert len(llm_started["data"]["request_fingerprint"]) == 64
    events = [event["event"] for event in trace.events]
    assert events == [
        "run_started",
        "llm_started",
        "llm_finished",
        "policy_decision",
        "tool_started",
        "tool_finished",
        "tool_result",
        "llm_started",
        "llm_finished",
        "run_finished",
    ]
    tool_event = next(e for e in trace.events if e["event"] == "tool_finished")
    assert tool_event["data"]["output"] == "echo:hello"
    policy_event = next(e for e in trace.events if e["event"] == "policy_decision")
    assert policy_event["data"]["risk"] == "unknown"


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
    agent.messages = [{
        "role": "tool",
        "tool_call_id": "old",
        "content": "\n".join("x" * 100 for _ in range(30)),
    }]

    assert agent._maybe_compress()
    event = next(item for item in trace.events if item["event"] == "context_compacted")
    assert event["data"]["strategy"] == "truncate"
    assert event["data"]["token_counter"] == "characters"
    assert event["data"]["fixed_tokens"] > 0
    assert event["data"]["before_tokens"] > event["data"]["after_tokens"]
    assert "tool_snip" in event["data"]["operations"]
    assert event["data"]["after_tokens"] == agent.context_tokens()
