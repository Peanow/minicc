import io
from types import SimpleNamespace

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from corecoder.terminal.approval import ApprovalDetails, ApprovalPrompt, redact_secret_text
from corecoder.terminal.app import TerminalApp
from corecoder.terminal.commands import default_registry
from corecoder.terminal.prompt import PromptState, SlashCompleter
from corecoder.terminal.render import EventRenderer


class FakeAgent:
    def __init__(self):
        self.llm = SimpleNamespace(
            model="fake-model",
            total_prompt_tokens=0,
            total_completion_tokens=0,
            estimated_cost=None,
        )
        self.changed_files = set()
        self.active_skills = set()
        self.skills = []


class FakeSessions:
    def list(self):
        return []


class FakeManager:
    def __init__(self):
        self.calls = 0

    def is_healthy(self, timeout=0.1):
        self.calls += 1
        return False


class FakePromptSession:
    def __init__(self, values):
        self.values = iter(values)

    def prompt(self, _message):
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value


def fake_bundle():
    return SimpleNamespace(
        agent=FakeAgent(),
        config=SimpleNamespace(
            model="fake-model",
            base_url=None,
            permission_mode="workspace-write",
            context_strategy="hybrid",
        ),
        history_file=None,
        manager=FakeManager(),
        sessions=FakeSessions(),
        workspace=".",
        ephemeral=True,
    )


def test_unknown_slash_command_is_consumed_and_literal_slash_is_not():
    output = io.StringIO()
    context = SimpleNamespace(console=Console(file=output, color_system=None))
    registry = default_registry()

    assert registry.dispatch("/does-not-exist", context)
    assert not registry.dispatch("//does-not-exist", context)
    assert "Unknown command" in output.getvalue()


def test_slash_completion_uses_registry_and_context_values():
    completer = SlashCompleter(
        default_registry(),
        {"model": lambda: ["model-a", "model-b"]},
    )
    commands = list(completer.get_completions(Document("/mo"), CompleteEvent()))
    models = list(completer.get_completions(Document("/model model-"), CompleteEvent()))

    assert [item.text for item in commands] == ["/model"]
    assert [item.text for item in models] == ["model-a", "model-b"]


def test_toolbar_render_is_pure_cached_state():
    state = PromptState(model="m", permission_mode="read-only", observability="OFF")
    first = state.toolbar()
    state.observability = "ON"
    second = state.toolbar()

    assert "OFF" in "".join(fragment[1] for fragment in first)
    assert "ON" in "".join(fragment[1] for fragment in second)


def test_plain_renderer_keeps_diagnostics_off_stdout():
    stdout, stderr = io.StringIO(), io.StringIO()
    renderer = EventRenderer("plain", stdout=stdout, stderr=stderr)
    renderer.emit({"kind": "text_delta", "data": {"text": "partial"}})
    renderer.emit({"kind": "tool_started", "data": {"tool": "read_file"}})
    renderer.finish({"status": "completed", "final_answer": "final", "changed_files": []})

    assert stdout.getvalue() == "final\n"
    assert "read_file" in stderr.getvalue()
    assert "partial" not in stdout.getvalue()


def test_approval_never_truncates_command_and_redacts_secrets():
    tail = "x" * 200
    command = f"curl -H 'Authorization: Bearer abcdefghijklmnop' {tail}"
    details = ApprovalDetails.legacy("bash", {"command": command}, "network")

    rendered = details.as_text(details=True)

    assert tail in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "[REDACTED_TOKEN]" in rendered
    assert redact_secret_text("API_KEY=top-secret") == "API_KEY=[REDACTED]"
    assert "top-secret" not in ApprovalDetails.legacy(
        "custom", {"api_key": "top-secret"}, "unknown"
    ).as_text(details=True)


def test_session_allow_is_only_offered_for_precise_rule():
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return "n"

    approval = ApprovalPrompt(
        console=Console(file=io.StringIO(), color_system=None),
        read=read,
    )
    approval.decide(ApprovalDetails.legacy("bash", {"command": "make"}, "execute"))

    assert "session" not in prompts[0]


def test_terminal_sends_double_slash_as_literal_without_stripping(monkeypatch):
    import corecoder.terminal.app as app_module

    sent = []

    def run_agent(_agent, prompt, observer):
        sent.append(prompt)
        observer({"kind": "run_started", "run_id": "r", "data": {}})
        return {
            "run_id": "r",
            "status": "completed",
            "final_answer": "ok",
            "changed_files": [],
        }

    monkeypatch.setattr(app_module, "run_agent", run_agent)
    bundle = fake_bundle()
    output = io.StringIO()
    app = TerminalApp(
        bundle,
        console=Console(file=output, width=80, color_system=None),
        prompt_session=FakePromptSession(["//literal  ", "/exit"]),
    )

    assert app.run() == 0
    assert sent == ["/literal  "]
    assert bundle.manager.calls == 2
