"""Tests for the cross-session memory system with semantic search."""

import json
import os
import tempfile
import time
from pathlib import Path

from corecoder.memory import (
    MemoryStore,
    Observation,
    extract_observations,
    format_memory_directory,
    format_memory_context,
    get_project_name,
    _hash,
    _vec_to_blob,
    blob_to_vec,
)


def test_memory_db_path_can_be_isolated_by_environment(tmp_path, monkeypatch):
    import corecoder.memory as memory_module

    isolated = tmp_path / "eval-memory.db"
    monkeypatch.setenv("CORECODER_MEMORY_DB", str(isolated))

    assert memory_module._db_path() == isolated.resolve()


# ---------------------------------------------------------------------------
# Observation dataclass
# ---------------------------------------------------------------------------

def test_observation_defaults():
    obs = Observation(title="test", content="hello")
    assert obs.kind == "observation"
    assert obs.type == "discovery"
    assert obs.files == []
    assert obs.score == 0.0


# ---------------------------------------------------------------------------
# Vector serialization
# ---------------------------------------------------------------------------

def test_vec_to_blob_and_back():
    vec = [0.1, 0.2, 0.3] + [0.0] * 509  # 512-dim
    blob = _vec_to_blob(vec, 512)
    assert blob is not None
    recovered = blob_to_vec(blob)
    assert len(recovered) == 512
    assert abs(recovered[0] - 0.1) < 1e-6
    assert abs(recovered[1] - 0.2) < 1e-6


def test_vec_to_blob_none():
    assert _vec_to_blob(None, 512) is None


def test_vec_to_blob_truncation():
    """Vector longer than dims gets truncated."""
    vec = [0.1] * 600
    blob = _vec_to_blob(vec, 512)
    recovered = blob_to_vec(blob)
    assert len(recovered) == 512


# ---------------------------------------------------------------------------
# MemoryStore — basic CRUD
# ---------------------------------------------------------------------------

def _make_store(tmpdir) -> MemoryStore:
    return MemoryStore(db_path=Path(tmpdir) / "test_memory.db", embedding_dims=512)


def test_save_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            obs = Observation(
                project="test/proj",
                kind="manual",
                type="discovery",
                title="Test observation",
                content="This is a test",
            )
            row_id = store.save(obs)
            assert row_id is not None
            assert row_id > 0

            recent = store.get_recent("test/proj")
            assert len(recent) == 1
            assert recent[0].title == "Test observation"
        finally:
            store.close()


def test_save_with_embedding():
    """save() accepts an embedding and stores it as BLOB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            obs = Observation(
                project="test/proj",
                title="Embedded obs",
                content="Has a vector",
            )
            embedding = [0.1] * 512
            row_id = store.save(obs, embedding=embedding)
            assert row_id is not None

            # verify embedding was stored
            row = store._conn.execute(
                "SELECT embedding FROM observations WHERE id = ?", (row_id,),
            ).fetchone()
            assert row["embedding"] is not None
            recovered = blob_to_vec(row["embedding"])
            assert len(recovered) == 512
            assert abs(recovered[0] - 0.1) < 1e-6
        finally:
            store.close()


def test_save_without_embedding():
    """save() without embedding stores NULL in embedding column."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            obs = Observation(
                project="test/proj",
                title="No embedding",
                content="Text only",
            )
            row_id = store.save(obs, embedding=None)
            assert row_id is not None

            row = store._conn.execute(
                "SELECT embedding FROM observations WHERE id = ?", (row_id,),
            ).fetchone()
            assert row["embedding"] is None
        finally:
            store.close()


def test_save_dedup():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            obs1 = Observation(project="test/proj", title="Same", content="identical content")
            obs2 = Observation(project="test/proj", title="Same", content="identical content")
            id1 = store.save(obs1)
            id2 = store.save(obs2)
            assert id1 is not None
            assert id2 is None
            assert store.count("test/proj") == 1
        finally:
            store.close()


def test_save_many_with_embeddings():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            obs_list = [
                Observation(project="test/proj", title=f"Obs {i}", content=f"Content {i}")
                for i in range(3)
            ]
            embeddings = [[0.1 * i] * 512 for i in range(3)]
            results = store.save_many(obs_list, embeddings=embeddings)
            assert all(r is not None for r in results)
            assert store.count("test/proj") == 3
        finally:
            store.close()


def test_project_isolation():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(Observation(project="proj/a", title="A1", content="a1"))
            store.save(Observation(project="proj/b", title="B1", content="b1"))
            assert store.count("proj/a") == 1
            assert store.count("proj/b") == 1
        finally:
            store.close()


# ---------------------------------------------------------------------------
# MemoryStore — FTS5 search
# ---------------------------------------------------------------------------

def test_search_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(Observation(
                project="test/proj", title="Auth module",
                content="Implemented JWT authentication with RS256",
            ))
            results = store.search("test/proj", "authentication")
            assert len(results) >= 1
            assert any("Auth" in o.title for o in results)
        finally:
            store.close()


def test_search_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            results = store.search("test/proj", "nonexistent")
            assert results == []
        finally:
            store.close()


# ---------------------------------------------------------------------------
# MemoryStore — semantic search
# ---------------------------------------------------------------------------

def test_semantic_search_basic():
    """Semantic search finds observations by vector similarity."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            # save two observations with different embeddings
            store.save(
                Observation(project="test/proj", title="Auth", content="JWT auth"),
                embedding=[1.0] + [0.0] * 511,  # points in direction [1, 0, ...]
            )
            store.save(
                Observation(project="test/proj", title="Database", content="PostgreSQL setup"),
                embedding=[0.0, 1.0] + [0.0] * 510,  # points in direction [0, 1, ...]
            )

            # query close to "Auth" embedding
            results = store.semantic_search("test/proj", [1.0] + [0.0] * 511, limit=5)
            assert len(results) >= 1
            assert results[0].title == "Auth"
            assert results[0].score > 0.9  # cosine similarity should be ~1.0
        finally:
            store.close()


def test_semantic_search_no_embeddings():
    """Semantic search returns empty when no embeddings stored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(Observation(
                project="test/proj", title="No vec", content="Text only",
            ))
            results = store.semantic_search("test/proj", [0.1] * 512, limit=5)
            assert results == []
        finally:
            store.close()


def test_semantic_search_scoped():
    """Semantic search is scoped by project."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(
                Observation(project="proj/a", title="A", content="a"),
                embedding=[1.0] + [0.0] * 511,
            )
            store.save(
                Observation(project="proj/b", title="B", content="b"),
                embedding=[1.0] + [0.0] * 511,
            )
            results = store.semantic_search("proj/a", [1.0] + [0.0] * 511, limit=5)
            assert len(results) == 1
            assert results[0].project == "proj/a"
        finally:
            store.close()


# ---------------------------------------------------------------------------
# MemoryStore — hybrid search
# ---------------------------------------------------------------------------

def test_hybrid_search_merges():
    """Hybrid search merges FTS5 and semantic results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            # observation with embedding but NOT matching FTS5
            store.save(
                Observation(
                    project="test/proj",
                    title="Vector only",
                    content="security authentication protocol",
                ),
                embedding=[1.0] + [0.0] * 511,
            )
            # observation matching FTS5 but no embedding
            store.save(Observation(
                project="test/proj",
                title="Keyword match",
                content="JWT authentication implementation",
            ))

            # hybrid: query "authentication" with embedding close to obs 1
            results = store.hybrid_search(
                "test/proj", "authentication",
                query_embedding=[1.0] + [0.0] * 511,
                limit=10,
            )
            # should get both (one from FTS5, one from semantic)
            assert len(results) >= 2
            titles = {o.title for o in results}
            assert "Vector only" in titles
            assert "Keyword match" in titles
        finally:
            store.close()


def test_hybrid_search_without_embedding():
    """Hybrid search falls back to FTS5 when no query embedding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(Observation(
                project="test/proj",
                title="FTS match",
                content="database connection pooling",
            ))
            results = store.hybrid_search("test/proj", "database", limit=5)
            assert len(results) >= 1
        finally:
            store.close()


# ---------------------------------------------------------------------------
# get_recent_titles
# ---------------------------------------------------------------------------

def test_get_recent_titles():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        try:
            store.save(Observation(
                project="test/proj", title="T1", content="C1", type="change",
                created_at="2026-01-01T00:00:00",
            ))
            store.save(Observation(
                project="test/proj", title="T2", content="C2", type="decision",
                created_at="2026-06-01T00:00:00",
            ))
            titles = store.get_recent_titles("test/proj")
            assert len(titles) == 2
            assert titles[0]["title"] == "T2"  # most recent first
            assert "content" not in titles[0]  # lightweight — no content
        finally:
            store.close()


# ---------------------------------------------------------------------------
# extract_observations
# ---------------------------------------------------------------------------

def test_extract_edited_files():
    messages = [
        {"role": "tool", "content": "Wrote src/app.py successfully"},
        {"role": "tool", "content": "Edited corecoder/agent.py: replaced loop logic"},
    ]
    obs = extract_observations(messages, project="test/proj")
    change_obs = [o for o in obs if o.type == "change"]
    assert len(change_obs) == 1
    assert "src/app.py" in change_obs[0].files
    assert "corecoder/agent.py" in change_obs[0].files


def test_extract_errors():
    messages = [
        {"role": "tool", "content": "Error: module 'numpy' not found in environment"},
    ]
    obs = extract_observations(messages, project="test/proj")
    error_obs = [o for o in obs if o.type == "bugfix"]
    assert len(error_obs) == 1
    assert "numpy" in error_obs[0].content


def test_extract_empty():
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
    obs = extract_observations(messages, project="test/proj")
    assert len(obs) == 0


# ---------------------------------------------------------------------------
# format_memory_directory (for system prompt)
# ---------------------------------------------------------------------------

def test_format_directory_empty():
    assert format_memory_directory([]) == ""


def test_format_directory_has_titles():
    titles = [
        {"id": 1, "type": "change", "title": "Modified 3 files", "created_at": "..."},
        {"id": 2, "type": "decision", "title": "Use SQLite", "created_at": "..."},
    ]
    result = format_memory_directory(titles)
    assert "# Memory" in result
    assert "memory_search" in result
    assert "[change] Modified 3 files" in result
    assert "[decision] Use SQLite" in result


# ---------------------------------------------------------------------------
# format_memory_context (for on-demand injection)
# ---------------------------------------------------------------------------

def test_format_context_empty():
    assert format_memory_context([]) == ""


def test_format_context_with_observations():
    obs_list = [
        Observation(
            type="change", title="Modified files",
            content="Changed: src/app.py",
            files=["src/app.py"],
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    ]
    result = format_memory_context(obs_list)
    assert "Relevant memories" in result
    assert "Modified files" in result


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

def test_hash_deterministic():
    h1 = _hash("proj", "title", "content")
    h2 = _hash("proj", "title", "content")
    assert h1 == h2


def test_hash_differs():
    h1 = _hash("proj", "title", "content A")
    h2 = _hash("proj", "title", "content B")
    assert h1 != h2


# ---------------------------------------------------------------------------
# get_project_name
# ---------------------------------------------------------------------------

def test_project_name_git_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        parent = Path(tmpdir) / "myorg"
        repo = parent / "myrepo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        name = get_project_name(cwd=repo)
        assert name == "myorg/myrepo"


def test_project_name_no_git():
    with tempfile.TemporaryDirectory() as tmpdir:
        name = get_project_name(cwd=tmpdir)
        assert name == Path(tmpdir).name


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------

def test_agent_has_memory_directory():
    """Agent loads lightweight memory directory at init."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM
    llm = LLM(model="test", api_key="test")
    agent = Agent(llm=llm)
    assert agent._project != ""
    assert isinstance(agent._memory_dir, str)


class _CapturingLLM:
    model = "test"
    estimated_cost = None

    def __init__(self):
        from corecoder.llm import LLMResponse

        self.calls = []
        self.response = LLMResponse(content="done", prompt_tokens=1, completion_tokens=1)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        self.total_prompt_tokens += self.response.prompt_tokens
        self.total_completion_tokens += self.response.completion_tokens
        return self.response


class _SequenceLLM:
    model = "test"
    estimated_cost = None

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        return response


class _SpyMemoryService:
    def __init__(self, tmp_path):
        from corecoder.embedding import EmbeddingService

        self.db_path = tmp_path / "memory.db"
        self.enabled = True
        self.writable = True
        self.embedding = EmbeddingService(provider="none")
        self.search_calls = 0
        self.save_conversation_calls = 0

    def recent_titles(self, limit=20):
        return [{"id": 1, "type": "decision", "title": "Historical decision"}]

    def search(self, query, limit=10):
        self.search_calls += 1
        return []

    def save_conversation(self, messages):
        self.save_conversation_calls += 1
        return 1

    def close(self):
        return None


def test_agent_does_not_auto_search_or_inject_memory(tmp_path):
    """A first task leaves historical retrieval to an explicit tool call."""
    from corecoder.agent import Agent
    from corecoder.paths import AppPaths
    from corecoder.trace import InMemoryTraceSink

    llm = _CapturingLLM()
    memory = _SpyMemoryService(tmp_path)
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=llm,
        tools=[],
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state"),
        memory_service=memory,
        trace=trace,
    )

    agent.run("work on the current task")

    assert memory.search_calls == 0
    sent = llm.calls[0]["messages"]
    assert len([message for message in sent if message["role"] == "system"]) == 1
    assert "Relevant memories" not in "\n".join(
        str(message.get("content", "")) for message in sent
    )
    assert not any(
        event["event"] == "memory_failed" and event["data"].get("operation") == "search"
        for event in trace.events
    )


def test_agent_close_does_not_auto_save_memory(tmp_path):
    """Closing an Agent does not persist conversation-derived observations."""
    from corecoder.agent import Agent
    from corecoder.paths import AppPaths
    from corecoder.trace import InMemoryTraceSink

    memory = _SpyMemoryService(tmp_path)
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=_CapturingLLM(),
        tools=[],
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state"),
        memory_service=memory,
        trace=trace,
    )
    agent.messages.append({"role": "user", "content": "a conversation"})
    agent.close()

    assert memory.save_conversation_calls == 0
    assert not (tmp_path / "memory.db").exists()
    assert not any(event["event"] == "memory_written" for event in trace.events)
    assert not any(event["event"] == "memory_failed" for event in trace.events)

    empty_memory = _SpyMemoryService(tmp_path / "empty")
    empty_agent = Agent(
        llm=_CapturingLLM(),
        tools=[],
        workspace=tmp_path / "empty",
        app_paths=AppPaths(tmp_path / "empty-state"),
        memory_service=empty_memory,
        trace=InMemoryTraceSink(),
    )
    empty_agent.close()
    assert empty_memory.save_conversation_calls == 0
    assert not empty_memory.db_path.exists()


def test_explicit_memory_tools_keep_schema_and_effects(tmp_path):
    """Explicit save/search remain available across Agent instances."""
    from corecoder.agent import Agent
    from corecoder.embedding import EmbeddingService
    from corecoder.llm import LLMResponse, ToolCall
    from corecoder.memory_service import MemoryService
    from corecoder.paths import AppPaths
    from corecoder.policy import ExecutionPolicy, PermissionMode
    from corecoder.tools import build_default_tools
    from corecoder.tools.base import Effect, ToolStatus
    from corecoder.trace import InMemoryTraceSink

    db_path = tmp_path / "shared-memory.db"
    service_a = MemoryService(
        db_path=db_path,
        project_id="shared/project",
        embedding=EmbeddingService(provider="none"),
    )
    trace = InMemoryTraceSink()
    agent_a = Agent(
        llm=_SequenceLLM([
            LLMResponse(
                tool_calls=[ToolCall(
                    id="save-1",
                    name="memory_save",
                    arguments={
                        "title": "Decision",
                        "content": "Use explicit memory",
                    },
                )],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            LLMResponse(content="saved", prompt_tokens=1, completion_tokens=1),
        ]),
        tools=build_default_tools(tmp_path),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state-a"),
        memory_service=service_a,
        trace=trace,
    )
    save_tool = agent_a.tool_registry.get("memory_save")
    search_tool = agent_a.tool_registry.get("memory_search")
    assert save_tool.schema()["function"]["parameters"] == save_tool.parameters
    assert search_tool.schema()["function"]["parameters"] == search_tool.parameters
    assert save_tool.parameters["required"] == ["title", "content"]
    assert search_tool.parameters["required"] == ["query"]
    assert save_tool.effects == frozenset({Effect.APP_STATE_WRITE})
    assert search_tool.effects == frozenset({Effect.READ_FS})
    assert ExecutionPolicy(PermissionMode.WORKSPACE_WRITE).evaluate(
        save_tool, {"title": "Decision", "content": "Use explicit memory"}
    ).decision.value == "allow"

    result = agent_a.run("save this explicit decision")
    assert result.status == "completed"
    assert any(
        event["event"] == "tool_started"
        and event["data"].get("tool") == "memory_save"
        for event in trace.events
    )
    assert any(
        event["event"] == "tool_finished"
        and event["data"].get("tool") == "memory_save"
        and event["data"].get("status") == ToolStatus.SUCCESS.value
        for event in trace.events
    )
    agent_a.close()

    service_b = MemoryService(
        db_path=db_path,
        project_id="shared/project",
        embedding=EmbeddingService(provider="none"),
    )
    agent_b = Agent(
        llm=_CapturingLLM(),
        tools=build_default_tools(tmp_path),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state-b"),
        memory_service=service_b,
    )
    found = agent_b.tool_registry.get("memory_search").execute(query="explicit memory")
    assert found.status is ToolStatus.SUCCESS
    assert "Decision" in found.content
    agent_b.close()


def test_memory_slash_commands_remain_explicit(tmp_path):
    from types import SimpleNamespace

    from corecoder.embedding import EmbeddingService
    from corecoder.memory_service import MemoryService
    from corecoder.terminal.commands import default_registry
    from rich.console import Console
    import io

    service = MemoryService(
        db_path=tmp_path / "slash-memory.db",
        project_id="slash/project",
        embedding=EmbeddingService(provider="none"),
    )
    output = io.StringIO()
    context = SimpleNamespace(
        agent=SimpleNamespace(memory=service),
        console=Console(file=output, color_system=None),
    )

    assert default_registry().dispatch("/memory save Keep this explicitly", context)
    assert service.search("explicitly")
    assert "(1, False)" in output.getvalue()
    service.close()


def test_system_prompt_with_memory_directory():
    """System prompt includes memory directory section."""
    from corecoder.prompt import system_prompt
    from corecoder.tools import build_default_tools

    prompt = system_prompt(build_default_tools(), memory_context="# Memory\nYou have 3 memory items. Use memory_search.")
    assert "Memory" in prompt
    assert "memory_search" in prompt


def test_system_prompt_no_memory():
    from corecoder.prompt import system_prompt
    from corecoder.tools import build_default_tools

    prompt = system_prompt(build_default_tools(), memory_context="")
    assert "Memory" not in prompt


def test_memory_directory_and_runtime_modes_remain_compatible(tmp_path):
    from corecoder.agent import Agent
    from corecoder.embedding import EmbeddingService
    from corecoder.memory_service import MemoryService
    from corecoder.paths import AppPaths
    from corecoder.policy import ExecutionPolicy, PermissionMode
    from corecoder.tools import build_default_tools
    from corecoder.tools.base import ToolStatus
    from corecoder.trace import InMemoryTraceSink

    db_path = tmp_path / "modes.db"
    writable = MemoryService(
        db_path=db_path,
        project_id="modes/project",
        embedding=EmbeddingService(provider="none"),
    )
    writable.save("Persisted title", "Persisted content")
    trace = InMemoryTraceSink()
    agent = Agent(
        llm=_CapturingLLM(),
        tools=build_default_tools(tmp_path),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "state"),
        memory_service=writable,
        trace=trace,
    )
    assert "memory_search" in agent._memory_dir
    assert "memory_save" in agent._memory_dir
    assert "Persisted title" in agent._memory_dir
    assert "Relevant memories" not in agent._system
    agent.close()
    assert not any(
        event["event"] in {"memory_written", "memory_failed"}
        for event in trace.events
    )

    read_only = Agent(
        llm=_CapturingLLM(),
        tools=build_default_tools(tmp_path),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "readonly-state"),
        memory_service=MemoryService(
            db_path=db_path,
            project_id="modes/project",
            embedding=EmbeddingService(provider="none"),
        ),
        ephemeral=False,
        policy=ExecutionPolicy(
            PermissionMode.READ_ONLY, workspace=tmp_path
        ),
    )
    denied = read_only.tool_registry.get("memory_save").execute(
        title="Denied", content="Should remain read only"
    )
    assert denied.status is ToolStatus.ERROR
    assert read_only.tool_registry.get("memory_search").execute(query="Persisted").status is ToolStatus.SUCCESS
    read_only.close()

    ephemeral_db = tmp_path / "ephemeral.db"
    ephemeral = Agent(
        llm=_CapturingLLM(),
        tools=build_default_tools(tmp_path),
        workspace=tmp_path,
        app_paths=AppPaths(tmp_path / "ephemeral-state"),
        memory_service=MemoryService(
            db_path=ephemeral_db,
            project_id="modes/project",
            embedding=EmbeddingService(provider="none"),
        ),
        ephemeral=True,
    )
    assert ephemeral.memory_service.enabled is False
    assert ephemeral.tool_registry.get("memory_save").execute(
        title="No", content="Persistence"
    ).status is ToolStatus.ERROR
    ephemeral.close()
    assert not ephemeral_db.exists()


# ---------------------------------------------------------------------------
# EmbeddingService — none mode
# ---------------------------------------------------------------------------

def test_embedding_service_none():
    from corecoder.embedding import EmbeddingService
    svc = EmbeddingService(provider="none")
    assert not svc.is_available()
    assert svc.embed("test") is None
    assert svc.embed_batch(["a", "b"]) == [None, None]
