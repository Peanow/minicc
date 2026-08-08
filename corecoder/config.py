"""Configuration - env vars and defaults."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


_API_KEY_ENV_NAMES = (
    "CORECODER_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
)
_CONFIG_ENV_NAMES = frozenset({
    *_API_KEY_ENV_NAMES,
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
    "CORECODER_CONTEXT_STRATEGY",
    "CORECODER_TOKENIZER",
})
_DOTENV_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*="
)


@dataclass(frozen=True)
class DotenvLoadResult:
    """Non-sensitive facts about the dotenv files considered during startup."""

    project_path: Path | None = None
    user_path: Path | None = None
    project_loaded: bool = False
    user_loaded: bool = False
    process_keys: frozenset[str] = frozenset()
    project_keys: frozenset[str] = frozenset()
    user_keys: frozenset[str] = frozenset()

    @property
    def sources(self) -> tuple[str, ...]:
        sources: list[str] = []
        if self.process_keys:
            sources.append("process_environment")
        if self.project_loaded:
            sources.append("project_env")
        if self.user_loaded:
            sources.append("user_env")
        if not sources:
            sources.append("defaults")
        return tuple(sources)

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(
            str(path)
            for path in (self.project_path, self.user_path)
            if path is not None
        )

    def source_for(self, key: str) -> str | None:
        if key in self.process_keys:
            return "process_environment"
        if key in self.project_keys:
            return "project_env"
        if key in self.user_keys:
            return "user_env"
        return None


def _find_project_env() -> Path | None:
    """Find the existing project/parent .env using the historical lookup."""
    try:
        env_path = Path(".env")
        if env_path.exists():
            return env_path
        cur = Path.cwd()
        home = Path.home()
        while cur != home and cur != cur.parent:
            candidate = cur / ".env"
            if candidate.exists():
                return candidate
            cur = cur.parent
    except OSError:
        return None
    return None


def _read_dotenv(path: Path | None, dotenv_values) -> dict[str, str]:
    if path is None:
        return {}
    try:
        values = dotenv_values(path)
        return {
            str(key): str(value)
            for key, value in values.items()
            if value is not None
        }
    except (OSError, ValueError):
        # An unreadable or malformed optional user file must not make startup
        # fail.  The existing environment/default behavior remains available.
        return {}


def _load_dotenv() -> DotenvLoadResult:
    """Load user and project dotenv files without overriding process env vars."""
    process_environment = dict(os.environ)
    process_keys = frozenset(_CONFIG_ENV_NAMES.intersection(process_environment))
    try:
        from dotenv import dotenv_values
    except ImportError:
        return DotenvLoadResult(process_keys=process_keys)

    user_path = Path.home() / ".corecoder" / ".env"
    project_path = _find_project_env()

    user_values = _read_dotenv(
        user_path if user_path.exists() else None,
        dotenv_values,
    )
    for key, value in user_values.items():
        if key not in process_environment:
            os.environ[key] = value

    project_values = _read_dotenv(project_path, dotenv_values)
    for key, value in project_values.items():
        # Project values outrank user values, but never process values.
        if key not in process_environment:
            os.environ[key] = value

    user_keys = frozenset(_CONFIG_ENV_NAMES.intersection(user_values))
    project_keys = frozenset(_CONFIG_ENV_NAMES.intersection(project_values))

    return DotenvLoadResult(
        project_path=project_path,
        user_path=user_path if user_path.exists() else None,
        project_loaded=bool(project_values),
        user_loaded=bool(user_values),
        process_keys=process_keys,
        project_keys=project_keys,
        user_keys=user_keys,
    )


def initialize_user_env(
    source: str | Path,
    target: str | Path | None = None,
) -> Path:
    """Create or supplement ``~/.corecoder/.env`` without exposing values.

    Existing target variables are preserved.  A newly created file is opened
    with mode ``0600`` and an existing file is tightened to that mode before
    any missing assignments are appended.
    """
    source_path = Path(source).expanduser().resolve()
    target_path = Path(target or (Path.home() / ".corecoder" / ".env")).expanduser()
    if source_path == target_path.resolve(strict=False):
        raise ValueError("source and target dotenv files must differ")

    source_text = source_path.read_text(encoding="utf-8")
    target_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    if not target_path.exists():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(target_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(source_text)
        finally:
            if descriptor != -1:
                os.close(descriptor)
        os.chmod(target_path, 0o600)
        return target_path

    existing_text = target_path.read_text(encoding="utf-8")
    existing_keys = {
        match.group("key")
        for line in existing_text.splitlines()
        if (match := _DOTENV_ASSIGNMENT.match(line))
    }
    missing_lines: list[str] = []
    for line in source_text.splitlines():
        match = _DOTENV_ASSIGNMENT.match(line)
        if match and match.group("key") not in existing_keys:
            missing_lines.append(line)
            existing_keys.add(match.group("key"))

    if missing_lines:
        separator = "" if not existing_text or existing_text.endswith("\n") else "\n"
        with target_path.open("a", encoding="utf-8") as handle:
            handle.write(separator + "\n".join(missing_lines) + "\n")
    os.chmod(target_path, 0o600)
    return target_path


@dataclass
class Config:
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    max_context_tokens: int = 128_000
    provider: str = "openai"
    embedding_provider: str = "none"      # "local" | "api" | "none"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dims: int = 512
    permission_mode: str = "workspace-write"
    context_strategy: str = "hybrid"
    tokenizer_provider: str = "auto"
    # Startup metadata is intentionally non-sensitive and excluded from the
    # normal dataclass representation so credentials cannot be printed by
    # accident.
    config_sources: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)
    config_files: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)
    api_key_source: str | None = field(default=None, repr=False, compare=False)

    def trace_metadata(self) -> dict[str, object]:
        """Return safe configuration facts suitable for a ``config_loaded`` trace."""
        return {
            "sources": list(self.config_sources),
            "dotenv_files": list(self.config_files),
            "api_key_configured": bool(self.api_key),
            "api_key_source": self.api_key_source or "none",
        }

    @classmethod
    def from_env(cls) -> "Config":
        # load .env if present (won't override existing env vars)
        dotenv = _load_dotenv() or DotenvLoadResult(
            process_keys=frozenset(_CONFIG_ENV_NAMES.intersection(os.environ)),
        )
        # pick up common env vars automatically
        api_key = ""
        api_key_source = None
        for key in _API_KEY_ENV_NAMES:
            value = os.getenv(key)
            if value:
                api_key = value
                api_key_source = dotenv.source_for(key)
                break
        return cls(
            model=os.getenv("CORECODER_MODEL", "gpt-4o"),
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("CORECODER_BASE_URL"),
            max_tokens=int(os.getenv("CORECODER_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("CORECODER_TEMPERATURE", "0")),
            max_context_tokens=int(os.getenv("CORECODER_MAX_CONTEXT", "128000")),
            provider=os.getenv("CORECODER_PROVIDER", "openai"),
            embedding_provider=os.getenv("CORECODER_EMBEDDING_PROVIDER", "none"),
            embedding_model=os.getenv("CORECODER_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            embedding_dims=int(os.getenv("CORECODER_EMBEDDING_DIMS", "512")),
            permission_mode=os.getenv("CORECODER_PERMISSION_MODE", "workspace-write"),
            context_strategy=os.getenv("CORECODER_CONTEXT_STRATEGY", "hybrid"),
            tokenizer_provider=os.getenv("CORECODER_TOKENIZER", "auto"),
            config_sources=dotenv.sources,
            config_files=dotenv.files,
            api_key_source=api_key_source,
        )
