"""Tests for local Phoenix control and OpenTelemetry span translation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ToolCall
from corecoder.observability import (
    DEFAULT_PHOENIX_IMAGE,
    ObservabilityConfig,
    ObservabilityError,
    PhoenixManager,
)
from corecoder.tools.base import Tool
from corecoder.trace import (
    CompositeTraceSink,
    InMemoryTraceSink,
    OpenTelemetryTraceSink,
    TraceSink,
)


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


class ParallelEchoTool(EchoTool):
    parallel_safe = True


class ToolLLM:
    model = "fake-model"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    estimated_cost = None

    def __init__(self):
        self.responses = [
            LLMResponse(
                tool_calls=[ToolCall(
                    id="call-1",
                    name="echo",
                    arguments={"text": "token=secret-value"},
                )],
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


class DoneLLM:
    model = "fake-model"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    estimated_cost = None

    def chat(self, **kwargs):
        return LLMResponse(content="done")


class ParallelToolLLM(ToolLLM):
    def __init__(self):
        self.responses = [
            LLMResponse(tool_calls=[
                ToolCall(id="call-a", name="echo", arguments={"text": "a"}),
                ToolCall(id="call-b", name="echo", arguments={"text": "b"}),
            ]),
            LLMResponse(content="done"),
        ]


class RaisingLLM(DoneLLM):
    def __init__(self, exception):
        self.exception = exception

    def chat(self, **kwargs):
        raise self.exception


def test_each_agent_task_has_a_new_run_in_the_same_session():
    sink = InMemoryTraceSink(session_id="session-1")
    agent = Agent(llm=DoneLLM(), tools=[], trace=sink)

    agent.chat("first")
    agent.chat("second")

    starts = [event for event in sink.events if event["event"] == "run_started"]
    assert len({event["run_id"] for event in starts}) == 2
    assert {event["session_id"] for event in starts} == {"session-1"}


@pytest.mark.parametrize(
    ("exception", "status"),
    [(RuntimeError("boom"), "error"), (KeyboardInterrupt(), "cancelled")],
)
def test_failed_and_cancelled_tasks_close_the_run(exception, status):
    sink = InMemoryTraceSink()
    agent = Agent(llm=RaisingLLM(exception), tools=[], trace=sink)

    with pytest.raises(type(exception)):
        agent.chat("fail")

    finished = [event for event in sink.events if event["event"] == "run_finished"]
    assert len(finished) == 1
    assert finished[0]["data"]["status"] == status


def test_max_rounds_closes_the_run():
    sink = InMemoryTraceSink()
    agent = Agent(llm=DoneLLM(), tools=[], trace=sink, max_rounds=0)
    assert agent.chat("stop") == "(reached maximum tool-call rounds)"
    assert sink.events[-1]["event"] == "run_finished"
    assert sink.events[-1]["data"]["status"] == "max_rounds"


def test_composite_sink_isolates_exporter_failures():
    class BrokenSink(TraceSink):
        def emit(self, event: str, **data):
            raise RuntimeError("collector unavailable")

    memory = InMemoryTraceSink()
    composite = CompositeTraceSink([memory, BrokenSink()])
    composite.begin_run("run-1")
    composite.emit("run_started", model="fake")
    composite.end_run()

    assert memory.events[0]["event"] == "run_started"
    assert memory.events[0]["run_id"] == "run-1"


def test_otel_sink_builds_agent_llm_and_tool_span_tree():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    sink = OpenTelemetryTraceSink(
        "http://unused/v1/traces",
        exporter=exporter,
        session_id="session-1",
    )
    agent = Agent(llm=ToolLLM(), tools=[EchoTool()], trace=sink)

    assert agent.chat("use echo") == "done"
    sink.close()

    spans = exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "invoke_agent corecoder")
    llm_spans = [span for span in spans if span.name == "chat fake-model"]
    tool = next(span for span in spans if span.name == "execute_tool echo")
    assert len(llm_spans) == 2
    assert all(span.parent.span_id == root.context.span_id for span in llm_spans)
    assert tool.parent.span_id == root.context.span_id
    assert tool.attributes["gen_ai.tool.call.id"] == "call-1"
    assert tool.attributes["corecoder.policy.decision"] == "allow"
    assert "secret-value" not in tool.attributes["input.value"]
    assert root.attributes["session.id"] == "session-1"
    assert root.attributes["corecoder.run.status"] == "completed"


def test_otel_metadata_only_omits_content():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    sink = OpenTelemetryTraceSink(
        "http://unused/v1/traces",
        content_policy="metadata-only",
        exporter=exporter,
    )
    agent = Agent(llm=DoneLLM(), tools=[], trace=sink)
    agent.chat("private prompt")
    sink.close()

    spans = exporter.get_finished_spans()
    assert all("input.value" not in span.attributes for span in spans)
    assert all("output.value" not in span.attributes for span in spans)


def test_parallel_same_name_tools_close_distinct_spans():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    sink = OpenTelemetryTraceSink("http://unused", exporter=exporter)
    agent = Agent(llm=ParallelToolLLM(), tools=[ParallelEchoTool()], trace=sink)
    agent.chat("parallel")
    sink.close()

    tools = [
        span for span in exporter.get_finished_spans()
        if span.name == "execute_tool echo"
    ]
    assert len(tools) == 2
    assert {span.attributes["gen_ai.tool.call.id"] for span in tools} == {
        "call-a", "call-b",
    }


def test_observability_config_validates_environment(monkeypatch):
    monkeypatch.delenv("CORECODER_PHOENIX_IMAGE", raising=False)
    monkeypatch.setenv("CORECODER_OBSERVABILITY", "otel")
    monkeypatch.setenv("CORECODER_TRACE_CONTENT", "metadata-only")
    monkeypatch.setenv("CORECODER_OBSERVABILITY_PROJECT", "tests")
    config = ObservabilityConfig.from_env()
    assert config.backend == "otel"
    assert config.content_policy == "metadata-only"
    assert config.project_name == "tests"
    assert config.phoenix_image == DEFAULT_PHOENIX_IMAGE

    monkeypatch.setenv("CORECODER_TRACE_CONTENT", "everything")
    with pytest.raises(ValueError, match="CORECODER_TRACE_CONTENT"):
        ObservabilityConfig.from_env()


def test_phoenix_up_is_idempotent(monkeypatch):
    manager = PhoenixManager(ObservabilityConfig())
    monkeypatch.setattr(manager, "is_healthy", lambda timeout=0.5: True)
    monkeypatch.setattr(
        manager,
        "_docker_ready",
        lambda: pytest.fail("Docker should not be inspected"),
    )
    assert manager.up() is False


def test_phoenix_health_check_bypasses_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    manager = PhoenixManager(ObservabilityConfig())

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    manager._urlopen = lambda url, timeout: Response()
    assert manager.is_healthy()


def test_local_otlp_export_adds_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.delenv("no_proxy", raising=False)
    manager = PhoenixManager(ObservabilityConfig())
    manager._ensure_local_otlp_bypasses_proxy()
    assert os.environ["NO_PROXY"] == "example.com,127.0.0.1,localhost,::1"
    assert os.environ["no_proxy"] == "127.0.0.1,localhost,::1"


def test_phoenix_reports_stopped_docker(monkeypatch):
    manager = PhoenixManager(ObservabilityConfig())
    monkeypatch.setattr("corecoder.observability.shutil.which", lambda name: "/docker")
    monkeypatch.setattr(
        manager,
        "_run",
        lambda command: subprocess.CompletedProcess(command, 1, "", "daemon down"),
    )
    with pytest.raises(ObservabilityError, match="Docker daemon is not running"):
        manager._docker_ready()


@pytest.mark.parametrize(
    ("detail", "message"),
    [
        (
            "connecting to localhost:7897: connect: connection refused",
            "local proxy",
        ),
        (
            "tls: first record does not look like a TLS handshake",
            "invalid TLS",
        ),
        (
            "unexpected commit digest sha256:bad",
            "corrupted image layer",
        ),
    ],
)
def test_phoenix_startup_errors_are_actionable(detail, message):
    assert message in PhoenixManager._startup_error(detail)


def test_phoenix_compose_start_waits_for_health(monkeypatch):
    manager = PhoenixManager(ObservabilityConfig(startup_timeout=1))
    health = iter([False, True])
    monkeypatch.setattr(manager, "is_healthy", lambda timeout=0.5: next(health))
    monkeypatch.setattr(manager, "_docker_ready", lambda: None)
    monkeypatch.setattr(manager, "_port_in_use", lambda: False)
    commands = []

    def run(command):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(manager, "_run", run)
    assert manager.up() is True
    assert commands[0][-2:] == ["up", "-d"]


def test_phoenix_down_preserves_volume(monkeypatch):
    manager = PhoenixManager(ObservabilityConfig())
    monkeypatch.setattr(manager, "_docker_ready", lambda: None)
    commands = []

    def run(command):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(manager, "_run", run)
    manager.down()
    assert commands[0][-1] == "down"
    assert "--volumes" not in commands[0]
    assert "-v" not in commands[0]


def test_observe_status_cli_does_not_require_an_api_key(monkeypatch, capsys):
    from corecoder.cli import main

    for name in ("OPENAI_API_KEY", "CORECODER_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(PhoenixManager, "is_healthy", lambda self: True)
    monkeypatch.setattr("sys.argv", ["corecoder", "observe", "status"])

    main()

    assert "Phoenix is running" in capsys.readouterr().out


def test_dev_script_enables_observability_before_first_task():
    script = Path(__file__).parents[1].joinpath("dev.sh").read_text()
    assert "corecoder --observe" in script
