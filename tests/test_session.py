import json
import os
import stat

import pytest

from corecoder.paths import AppPaths, normalize_project_root, project_id_for
from corecoder.session import SCHEMA_VERSION, SessionError, SessionStore


def _project(tmp_path, name="project"):
    project = tmp_path / name
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _store(tmp_path, project=None):
    project = project or _project(tmp_path)
    return SessionStore(AppPaths(tmp_path / "app-home"), project)


def test_app_paths_use_injected_or_environment_home(tmp_path, monkeypatch):
    injected = AppPaths(tmp_path / "injected")
    assert injected.root == (tmp_path / "injected").resolve()
    assert injected.projects == injected.root / "projects"

    monkeypatch.setenv("CORECODER_HOME", str(tmp_path / "from-env"))
    configured = AppPaths()
    assert configured.root == (tmp_path / "from-env").resolve()


def test_project_paths_are_stable_for_nested_git_workspace(tmp_path):
    project = _project(tmp_path)
    nested = project / "src" / "package"
    nested.mkdir(parents=True)
    paths = AppPaths(tmp_path / "app-home")

    assert normalize_project_root(nested) == project.resolve()
    assert project_id_for(nested) == project_id_for(project)

    scoped = paths.for_project(nested)
    assert scoped.project_id == project_id_for(project)
    assert scoped.project_dir == paths.projects / scoped.project_id
    assert scoped.sessions_dir == scoped.project_dir / "sessions"
    assert scoped.history_path == scoped.project_dir / "history"
    assert scoped.history_file == scoped.history_path / "prompt.history"
    assert scoped.memory_dir == scoped.project_dir / "memory"
    assert scoped.trace_dir == scoped.project_dir / "trace"


def test_git_file_marks_a_worktree_root(tmp_path):
    worktree = tmp_path / "worktree"
    child = worktree / "child"
    child.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../git/worktrees/example\n")

    assert normalize_project_root(child) == worktree.resolve()


def test_save_load_schema_v2_and_private_permissions(tmp_path):
    store = _store(tmp_path)
    messages = [{"role": "user", "content": "hello"}]

    saved = store.save(
        messages,
        "model-a",
        "my-session",
        context_strategy="sliding",
        active_skills=["python"],
        last_run_status="completed",
    )
    loaded = store.load("my-session")

    assert loaded == saved
    assert loaded is not None
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.project_id == store.project_id
    assert loaded.context_strategy == "sliding"
    assert loaded.active_skills == ["python"]
    assert loaded.messages == messages
    assert loaded.created_at == loaded.updated_at

    path = store.sessions_dir / "my-session.json"
    raw = json.loads(path.read_text())
    assert list(raw)[0] == "schema_version"
    assert set(raw) == {
        "schema_version",
        "id",
        "project_id",
        "created_at",
        "updated_at",
        "model",
        "context_strategy",
        "active_skills",
        "messages",
        "last_run_status",
    }
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path, monkeypatch):
    store = _store(tmp_path)
    real_replace = os.replace
    observed = {}

    def inspect_replace(source, destination):
        source_path = type(store.sessions_dir)(source)
        observed["same_parent"] = source_path.parent == store.sessions_dir
        observed["source_exists"] = source_path.exists()
        real_replace(source, destination)

    monkeypatch.setattr("corecoder.session.os.replace", inspect_replace)
    store.save([{"role": "user", "content": "atomic"}], "model", "atomic")

    assert observed == {"same_parent": True, "source_exists": True}
    assert not list(store.sessions_dir.glob("*.tmp"))


def test_updating_session_preserves_creation_time_and_list_orders_by_update(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    timestamps = iter(
        [
            "2026-08-08T01:00:00.000000Z",
            "2026-08-08T02:00:00.000000Z",
            "2026-08-08T03:00:00.000000Z",
        ]
    )
    monkeypatch.setattr("corecoder.session._utc_now", lambda: next(timestamps))

    first = store.save([], "a", "first")
    store.save([], "b", "second")
    updated = store.save([{"role": "user", "content": "new"}], "c", "first")

    assert updated.created_at == first.created_at
    assert updated.updated_at == "2026-08-08T03:00:00.000000Z"
    assert [item.id for item in store.list()] == ["first", "second"]
    assert store.latest() == updated


def test_saving_a_record_does_not_mutate_the_callers_checkpoint(tmp_path, monkeypatch):
    store = _store(tmp_path)
    original = store.save([], "a", "checkpoint")
    original_updated_at = original.updated_at
    monkeypatch.setattr(
        "corecoder.session._utc_now", lambda: "2026-08-08T04:00:00.000000Z"
    )

    saved = store.save(original)

    assert original.updated_at == original_updated_at
    assert saved.updated_at == "2026-08-08T04:00:00.000000Z"
    assert store.load("checkpoint") == saved


def test_default_session_ids_do_not_collide(tmp_path):
    store = _store(tmp_path)
    first = store.save([{"role": "user", "content": "first"}], "model-a")
    second = store.save([{"role": "user", "content": "second"}], "model-b")

    assert first.id != second.id
    assert store.load(first.id) == first
    assert store.load(second.id) == second


def test_projects_are_isolated_even_for_the_same_session_id(tmp_path):
    app_paths = AppPaths(tmp_path / "app-home")
    first_project = _project(tmp_path, "first")
    second_project = _project(tmp_path, "second")
    first = SessionStore(app_paths, first_project)
    second = SessionStore(app_paths, second_project)

    first.save([{"role": "user", "content": "first"}], "model", "shared")

    assert first.sessions_dir != second.sessions_dir
    assert second.load("shared") is None
    assert second.list() == []


def test_project_mismatch_is_rejected(tmp_path):
    app_paths = AppPaths(tmp_path / "app-home")
    first = SessionStore(app_paths, _project(tmp_path, "first"))
    second = SessionStore(app_paths, _project(tmp_path, "second"))
    saved = first.save([], "model", "shared")
    second.sessions_dir.mkdir(parents=True)
    target = second.sessions_dir / "shared.json"
    target.write_text(json.dumps(saved.to_dict()))

    with pytest.raises(SessionError, match="different project"):
        second.load("shared")


def test_corrupt_json_raises_friendly_error_without_deleting_file(tmp_path):
    store = _store(tmp_path)
    store.sessions_dir.mkdir(parents=True)
    path = store.sessions_dir / "broken.json"
    path.write_text("{definitely not json")

    with pytest.raises(SessionError, match="invalid JSON"):
        store.load("broken")

    assert path.exists()
    assert path.read_text() == "{definitely not json"


def test_invalid_schema_has_a_clear_error(tmp_path):
    store = _store(tmp_path)
    store.sessions_dir.mkdir(parents=True)
    path = store.sessions_dir / "old.json"
    path.write_text(json.dumps({"id": "old", "messages": []}))

    with pytest.raises(SessionError, match="unsupported schema version"):
        store.load("old")
    assert path.exists()


def test_delete_reports_whether_a_session_existed(tmp_path):
    store = _store(tmp_path)
    store.save([], "model", "delete-me")

    assert store.delete("delete-me") is True
    assert store.delete("delete-me") is False
    assert store.load("delete-me") is None


def test_session_name_is_sanitized_without_escaping_project(tmp_path):
    store = _store(tmp_path)
    saved = store.save([], "model", "../Research Notes!")

    assert saved.id == "Research-Notes"
    assert store.load("../Research Notes!") == saved
    assert (store.sessions_dir / "Research-Notes.json").exists()


def test_session_checkpoint_redacts_credentials(tmp_path):
    store = _store(tmp_path)
    store.save(
        [{"role": "user", "content": "OPENAI_API_KEY=super-secret-value"}],
        "test-model",
        "secret",
    )
    path = store.sessions_dir / "secret.json"
    assert "super-secret-value" not in path.read_text()
