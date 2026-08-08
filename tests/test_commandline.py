import io
import json
from argparse import Namespace

import pytest

from corecoder.commandline.handlers import resolve_prompt
from corecoder.commandline.parser import build_parser


def test_new_command_tree_and_runtime_options_before_or_after_run():
    parser = build_parser()

    before = parser.parse_args(["--model", "alpha", "run", "hello"])
    after = parser.parse_args(["run", "hello", "--model", "beta"])
    replay = parser.parse_args(["trace", "replay", "run.jsonl"])
    evaluation = parser.parse_args(["lab", "eval", "manifest.json", "--dry-run"])

    assert (before.command, before.model, before.prompt) == ("run", "alpha", "hello")
    assert (after.command, after.model, after.prompt) == ("run", "beta", "hello")
    assert (replay.command, replay.trace_command) == ("trace", "replay")
    assert (evaluation.command, evaluation.lab_command) == ("lab", "eval")


def test_sandbox_network_cli_option_is_available_before_and_after_run():
    parser = build_parser()
    before = parser.parse_args(["--sandbox-network", "allow", "run", "hello"])
    after = parser.parse_args(["run", "hello", "--sandbox-network", "deny"])
    assert before.sandbox_network == "allow"
    assert after.sandbox_network == "deny"


@pytest.mark.parametrize(
    "argv",
    [
        ["-p", "hello"],
        ["-r", "session-id"],
        ["--api-key", "secret"],
        ["replay", "run.jsonl"],
        ["eval", "manifest.json"],
    ],
)
def test_removed_cli_entrypoints_are_rejected(argv):
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(argv)
    assert raised.value.code == 2


def _run_args(prompt=None, prompt_file=None):
    return Namespace(prompt=prompt, prompt_file=prompt_file)


def test_prompt_resolution_preserves_user_whitespace():
    value = resolve_prompt(_run_args(prompt="  keep me\n"), io.StringIO(""))
    assert value == "  keep me\n"


def test_prompt_resolution_rejects_multiple_sources():
    with pytest.raises(ValueError, match="exactly one"):
        resolve_prompt(_run_args(prompt="argument"), io.StringIO("pipe"))


def test_prompt_resolution_supports_explicit_stdin():
    value = resolve_prompt(
        _run_args(prompt_file="-"),
        io.StringIO("line one\nline two\n"),
    )
    assert value == "line one\nline two\n"


def test_jsonl_contract_has_required_keys():
    from corecoder.terminal.render import EventRenderer

    output = io.StringIO()
    renderer = EventRenderer("jsonl", stdout=output, stderr=io.StringIO())
    renderer.emit({
        "kind": "RunStarted",
        "run_id": "run-1",
        "timestamp": 1.5,
        "data": {"model": "test"},
    })
    renderer.finish({
        "run_id": "run-1",
        "status": "completed",
        "final_answer": "done",
        "changed_files": [],
        "prompt_tokens": 2,
        "completion_tokens": 3,
    })

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["event"] for record in records] == ["run_started", "run_finished"]
    assert all(set(record) == {"schema", "event", "run_id", "timestamp", "data"} for record in records)
    assert records[-1]["data"]["token"]["total"] == 5


def test_runtime_adapter_consumes_agent_observer_api(tmp_path):
    from corecoder.agent import Agent
    from corecoder.commandline.runtime import run_agent
    from corecoder.llm import LLMResponse
    from corecoder.paths import AppPaths

    class FakeLLM:
        model = "fake"
        total_prompt_tokens = 0
        total_completion_tokens = 0
        estimated_cost = None

        def chat(self, *, messages, tools=None, on_token=None):
            if on_token:
                on_token("hello")
            self.total_prompt_tokens += 4
            self.total_completion_tokens += 1
            return LLMResponse(
                content="hello",
                prompt_tokens=4,
                completion_tokens=1,
            )

    agent = Agent(
        llm=FakeLLM(),
        tools=[],
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state"),
        ephemeral=True,
    )
    events = []
    try:
        result = run_agent(agent, "say hello", events.append)
    finally:
        agent.close()

    kinds = [str(getattr(event.kind, "value", event.kind)) for event in events]
    assert kinds == [
        "run_started", "model_started", "text_delta", "model_finished", "run_finished"
    ]
    assert result.final_answer == "hello"
    assert result.token.total == 5
