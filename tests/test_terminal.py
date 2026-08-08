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
from corecoder.session import SessionRecord
from corecoder.trace import InMemoryTraceSink


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
        self.trace = InMemoryTraceSink()


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
        {
            "model": lambda: ["model-a", "model-b"],
            "session": lambda: ["resume-one", "other-two"],
        },
    )
    commands = list(completer.get_completions(Document("/mo"), CompleteEvent()))
    models = list(completer.get_completions(Document("/model model-"), CompleteEvent()))
    sessions = list(completer.get_completions(Document("/resume res"), CompleteEvent()))

    assert [item.text for item in commands] == ["/model"]
    assert [item.text for item in models] == ["model-a", "model-b"]
    assert [item.text for item in sessions] == ["resume-one"]


def _resumed_record(session_id="restored"):
    return SessionRecord(
        id=session_id,
        project_id="project",
        created_at="2026-08-08T00:00:00Z",
        updated_at="2026-08-08T00:01:00Z",
        model="restored-model",
        context_strategy="hybrid",
        messages=[
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "tool output",
            },
        ],
    )


def test_resume_renders_all_session_messages():
    output = io.StringIO()
    bundle = fake_bundle()
    app = TerminalApp(
        bundle,
        console=Console(file=output, width=100, color_system=None),
        prompt_session=FakePromptSession(["/exit"]),
        initial_session=_resumed_record(),
    )

    assert app.run() == 0
    rendered = output.getvalue()
    assert "first question" in rendered
    assert "first answer" in rendered
    assert "tool output" in rendered
    assert "call-1" in rendered
    assert rendered.index("first question") < rendered.index("first answer") < rendered.index("tool output")


def test_resume_slash_command_accepts_latest_or_id():
    output = io.StringIO()
    latest = _resumed_record("latest")
    named = _resumed_record("named")

    class Sessions:
        def __init__(self):
            self.loaded = []
            self.restored = []

        def latest(self):
            self.loaded.append("latest")
            return latest

        def load(self, session_id):
            self.loaded.append(session_id)
            return named

        def restore(self, agent, record):
            self.restored.append(record.id)

    bundle = fake_bundle()
    bundle.sessions = Sessions()
    app = TerminalApp(
        bundle,
        console=Console(file=output, width=100, color_system=None),
        prompt_session=FakePromptSession([]),
    )

    assert default_registry().dispatch("/resume", app)
    assert default_registry().dispatch("/resume named", app)
    assert bundle.sessions.loaded == ["latest", "named"]
    assert bundle.sessions.restored == ["latest", "named"]
    assert "first question" in output.getvalue()


def test_resume_trace_contains_metadata_only():
    output = io.StringIO()
    bundle = fake_bundle()
    app = TerminalApp(
        bundle,
        console=Console(file=output, width=100, color_system=None),
        prompt_session=FakePromptSession([]),
    )

    app._show_resumed_session(_resumed_record())

    event = [
        item for item in bundle.agent.trace.events if item["event"] == "session_resumed"
    ][-1]
    assert event["data"] == {
        "session_id": "restored",
        "message_count": 3,
        "model": "restored-model",
    }
    assert "first question" not in str(event)


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


def test_pretty_renderer_shows_approval_outcome():
    output = io.StringIO()
    renderer = EventRenderer(
        "pretty",
        stdout=output,
        width=80,
        no_color=True,
    )

    renderer.emit({
        "kind": "approval_decided",
        "data": {"tool": "bash", "outcome": "once"},
    })

    assert "approved   once" in output.getvalue()


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


def test_approval_selector_uses_safe_default_and_details():
    selections = iter(["details", "session"])
    calls = []
    output = io.StringIO()

    def select(message, options, default):
        calls.append((message, list(options), default))
        return next(selections)

    approval = ApprovalPrompt(
        console=Console(file=output, color_system=None),
        selector=select,
    )
    details = ApprovalDetails(
        tool="bash",
        arguments={"command": "make API_KEY=top-secret"},
        reason="workspace code execution requires approval",
        effect="EXECUTE",
        risk="workspace-execution",
        cwd="/workspace",
        reusable_rule="bash exact: make API_KEY=top-secret",
    )

    assert approval.decide(details).value == "session"
    assert all(call[2] == "deny" for call in calls)
    assert [value for value, _label in calls[0][1]] == [
        "once", "session", "details", "deny",
    ]
    assert "Approval details" in output.getvalue()
    assert "top-secret" not in output.getvalue()
    assert "[REDACTED]" in output.getvalue()


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
