"""Configuration precedence, initialization, and startup Trace coverage."""

import json
import os
import stat
from argparse import Namespace

from corecoder.config import Config, initialize_user_env


_CONFIG_KEYS = (
    "CORECODER_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "CORECODER_MODEL",
    "OPENAI_BASE_URL",
    "CORECODER_BASE_URL",
    "CORECODER_MAX_TOKENS",
    "CORECODER_TEMPERATURE",
    "CORECODER_MAX_CONTEXT",
    "CORECODER_PROVIDER",
    "CORECODER_EMBEDDING_PROVIDER",
    "CORECODER_EMBEDDING_MODEL",
    "CORECODER_EMBEDDING_DIMS",
    "CORECODER_PERMISSION_MODE",
    "CORECODER_SANDBOX_NETWORK",
    "CORECODER_CONTEXT_STRATEGY",
    "CORECODER_TOKENIZER",
)


def _clear_config_environment(monkeypatch):
    for key in _CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_user_dotenv_can_supply_api_key(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder").mkdir(parents=True)
    workspace.mkdir()
    (home / ".corecoder" / ".env").write_text(
        "OPENAI_API_KEY=user-key\nCORECODER_MODEL=user-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)

    config = Config.from_env()

    assert config.api_key == "user-key"
    assert config.model == "user-model"
    assert config.api_key_source == "user_env"
    assert config.trace_metadata()["api_key_configured"] is True


def test_sandbox_network_configuration_sources(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)
    monkeypatch.setenv("CORECODER_SANDBOX_NETWORK", "allow")

    config = Config.from_env()

    assert config.sandbox_network == "allow"

    from corecoder.commandline.runtime import apply_runtime_options

    apply_runtime_options(config, Namespace(sandbox_network="deny"))
    assert config.sandbox_network == "deny"


def test_project_dotenv_overrides_user_dotenv(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder").mkdir(parents=True)
    workspace.mkdir()
    (home / ".corecoder" / ".env").write_text(
        "OPENAI_API_KEY=user-key\nCORECODER_MODEL=user-model\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        "CORECODER_MODEL=project-model\nCORECODER_MAX_TOKENS=123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)

    config = Config.from_env()

    assert config.api_key == "user-key"
    assert config.model == "project-model"
    assert config.max_tokens == 123


def test_process_environment_overrides_both_dotenv_files(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder").mkdir(parents=True)
    workspace.mkdir()
    (home / ".corecoder" / ".env").write_text(
        "OPENAI_API_KEY=user-key\nCORECODER_MODEL=user-model\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        "OPENAI_API_KEY=project-key\nCORECODER_MODEL=project-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    monkeypatch.setenv("CORECODER_MODEL", "process-model")

    config = Config.from_env()

    assert config.api_key == "process-key"
    assert config.model == "process-model"
    assert config.api_key_source == "process_environment"


def test_missing_user_dotenv_preserves_project_and_default_behavior(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    (workspace / ".env").write_text(
        "OPENAI_API_KEY=project-key\nCORECODER_MODEL=project-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)

    config = Config.from_env()

    assert config.api_key == "project-key"
    assert config.model == "project-model"
    assert config.config_sources == ("project_env",)


def test_empty_user_dotenv_is_ignored(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder").mkdir(parents=True)
    workspace.mkdir()
    (home / ".corecoder" / ".env").write_text("\n# intentionally empty\n", encoding="utf-8")
    (workspace / ".env").write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)

    config = Config.from_env()

    assert config.api_key == "project-key"
    assert "user_env" not in config.config_sources


def test_unreadable_user_dotenv_is_ignored(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder" / ".env").mkdir(parents=True)
    workspace.mkdir()
    (workspace / ".env").write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)

    config = Config.from_env()

    assert config.api_key == "project-key"
    assert "user_env" not in config.config_sources


def test_initialize_user_env_is_private_and_only_supplements_existing_values(
    tmp_path,
):
    source = tmp_path / "project.env"
    target = tmp_path / "home" / ".corecoder" / ".env"
    source.write_text(
        "CORECODER_MODEL=source-model\nOPENAI_API_KEY=source-key\n",
        encoding="utf-8",
    )

    created = initialize_user_env(source, target)

    assert created == target
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    target.write_text("CORECODER_MODEL=existing-model\n", encoding="utf-8")
    initialize_user_env(source, target)
    content = target.read_text(encoding="utf-8")
    assert "CORECODER_MODEL=existing-model" in content
    assert "CORECODER_MODEL=source-model" not in content
    assert "OPENAI_API_KEY=source-key" in content
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_runtime_emits_safe_config_loaded_trace(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / ".corecoder").mkdir(parents=True)
    workspace.mkdir()
    secret = "trace-secret-value"
    (home / ".corecoder" / ".env").write_text(
        f"OPENAI_API_KEY={secret}\nCORECODER_MODEL=trace-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CORECODER_HOME", str(home / ".corecoder"))
    monkeypatch.setenv("CORECODER_OBSERVABILITY", "off")
    monkeypatch.chdir(workspace)
    _clear_config_environment(monkeypatch)
    trace_path = tmp_path / "startup.jsonl"

    from corecoder.commandline.runtime import build_runtime

    bundle = build_runtime(
        Namespace(trace=str(trace_path), observe=False),
        workspace=workspace,
        ephemeral=True,
    )
    try:
        pass
    finally:
        bundle.close()

    records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    config_event = next(record for record in records if record["event"] == "config_loaded")
    assert config_event["data"]["api_key_configured"] is True
    assert config_event["data"]["api_key_source"] == "user_env"
    assert secret not in trace_path.read_text()
