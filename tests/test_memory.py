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
    assert not agent._memory_injected


def test_agent_on_demand_injection(tmp_path, monkeypatch):
    """First chat() triggers semantic memory injection."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM
    from corecoder.memory import MemoryStore
    import corecoder.memory as memory_module

    monkeypatch.setattr(memory_module, "_MEMORY_DIR", tmp_path / "memory")

    llm = LLM(model="test", api_key="test")
    agent = Agent(llm=llm, embedding=None)
    assert not agent._memory_injected

    # save some memory for the project
    store = MemoryStore()
    try:
        import uuid
        unique = uuid.uuid4().hex[:8]
        store.save(Observation(
            project=agent._project,
            title=f"Test {unique}",
            content=f"Test content {unique}",
        ))
    finally:
        store.close()

    # After _inject_relevant_memory, flag should be set
    # (can't easily test the full chat() without a real LLM, but test the method)
    agent.messages = []
    agent._inject_relevant_memory("test query")
    assert agent._memory_injected


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


# ---------------------------------------------------------------------------
# EmbeddingService — none mode
# ---------------------------------------------------------------------------

def test_embedding_service_none():
    from corecoder.embedding import EmbeddingService
    svc = EmbeddingService(provider="none")
    assert not svc.is_available()
    assert svc.embed("test") is None
    assert svc.embed_batch(["a", "b"]) == [None, None]
