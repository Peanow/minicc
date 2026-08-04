"""Local OpenTelemetry/Phoenix observability service integration."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import webbrowser
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .trace import OpenTelemetryTraceSink


DEFAULT_PHOENIX_IMAGE = (
    "registry-1.docker.io/arizephoenix/phoenix:version-17.5.0"
)


@dataclass
class ObservabilityConfig:
    backend: str = "off"
    otlp_endpoint: str = "http://127.0.0.1:6006/v1/traces"
    ui_url: str = "http://127.0.0.1:6006"
    project_name: str = "corecoder"
    content_policy: str = "full"
    # Use Docker Hub's explicit registry hostname. A bare Docker Hub image can
    # be silently routed through globally configured registry mirrors, which
    # may return invalid TLS responses or corrupted layers.
    phoenix_image: str = DEFAULT_PHOENIX_IMAGE
    startup_timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "ObservabilityConfig":
        backend = os.getenv("CORECODER_OBSERVABILITY", "off").lower()
        content_policy = os.getenv("CORECODER_TRACE_CONTENT", "full").lower()
        if backend not in {"off", "otel"}:
            raise ValueError("CORECODER_OBSERVABILITY must be 'off' or 'otel'")
        if content_policy not in {"full", "metadata-only"}:
            raise ValueError(
                "CORECODER_TRACE_CONTENT must be 'full' or 'metadata-only'"
            )
        return cls(
            backend=backend,
            otlp_endpoint=os.getenv(
                "CORECODER_OTLP_ENDPOINT",
                "http://127.0.0.1:6006/v1/traces",
            ),
            ui_url=os.getenv(
                "CORECODER_OBSERVABILITY_UI",
                "http://127.0.0.1:6006",
            ).rstrip("/"),
            project_name=os.getenv(
                "CORECODER_OBSERVABILITY_PROJECT", "corecoder"
            ),
            content_policy=content_policy,
            phoenix_image=os.getenv(
                "CORECODER_PHOENIX_IMAGE",
                DEFAULT_PHOENIX_IMAGE,
            ),
            startup_timeout=float(
                os.getenv("CORECODER_OBSERVABILITY_TIMEOUT", "120")
            ),
        )


class ObservabilityError(RuntimeError):
    """An actionable local observability startup failure."""


class PhoenixManager:
    """Own idempotent Docker Compose lifecycle commands for local Phoenix."""

    project = "corecoder-observability"

    def __init__(self, config: ObservabilityConfig):
        self.config = config
        # Local control traffic must never inherit HTTP(S)_PROXY. Developer
        # shells commonly use a proxy for model APIs, and routing localhost
        # health checks through it makes a healthy Phoenix look unavailable.
        self._urlopen = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        ).open

    @property
    def health_url(self) -> str:
        return f"{self.config.ui_url}/healthz"

    @property
    def compose_path(self) -> Path:
        return Path(resources.files("corecoder").joinpath("observability-compose.yml"))

    def is_healthy(self, timeout: float = 0.5) -> bool:
        try:
            with self._urlopen(self.health_url, timeout=timeout) as response:
                return 200 <= response.status < 300
        except (OSError, urllib.error.URLError):
            return False

    def _compose_command(self, *args: str) -> list[str]:
        return [
            "docker", "compose", "-p", self.project,
            "-f", str(self.compose_path), *args,
        ]

    def _run(self, command: list[str]) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CORECODER_PHOENIX_IMAGE"] = self.config.phoenix_image
        return subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.config.startup_timeout,
            check=False,
        )

    @staticmethod
    def _startup_error(detail: str) -> str:
        lower = detail.lower()
        if (
            "connect: connection refused" in lower
            and ("localhost:" in lower or "127.0.0.1:" in lower)
        ):
            return (
                "Docker Desktop is configured to use a local proxy that is not "
                "running. Fix Docker Desktop > Settings > Resources > Proxies, "
                "then retry."
            )
        if "first record does not look like a tls handshake" in lower:
            return (
                "Docker's configured proxy or registry mirror returned invalid "
                "TLS data. Verify the Docker Desktop proxy port or disable the "
                "broken registry mirror, then retry."
            )
        if "unexpected commit digest" in lower:
            return (
                "A configured Docker registry mirror returned a corrupted image "
                "layer. CoreCoder now uses Docker Hub's explicit registry; retry "
                "or override CORECODER_PHOENIX_IMAGE with a trusted registry."
            )
        return "Failed to start Phoenix with Docker Compose."

    def _docker_ready(self):
        if shutil.which("docker") is None:
            raise ObservabilityError(
                "Docker is not installed. Install Docker Desktop and retry."
            )
        try:
            result = self._run(["docker", "info"])
        except subprocess.TimeoutExpired as exc:
            raise ObservabilityError("Docker did not respond before timeout.") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ObservabilityError(
                "Docker daemon is not running. Start Docker Desktop and retry."
                + (f"\n{detail}" if detail else "")
            )

    def _port_in_use(self) -> bool:
        parsed = urlparse(self.config.ui_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            return False

    def up(self) -> bool:
        """Ensure Phoenix is healthy. Return True when it was newly started."""
        if self.is_healthy():
            return False
        self._docker_ready()
        if self._port_in_use():
            raise ObservabilityError(
                f"The observability port for {self.config.ui_url} is already in use "
                "by a service that is not Phoenix."
            )
        try:
            result = self._run(self._compose_command("up", "-d"))
        except subprocess.TimeoutExpired as exc:
            raise ObservabilityError(
                "Phoenix image download/startup exceeded the configured timeout."
            ) from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ObservabilityError(
                self._startup_error(detail)
                + (f"\n{detail}" if detail else "")
            )

        deadline = time.monotonic() + self.config.startup_timeout
        while time.monotonic() < deadline:
            if self.is_healthy():
                return True
            time.sleep(0.25)
        raise ObservabilityError(
            f"Phoenix did not become healthy at {self.health_url} "
            f"within {self.config.startup_timeout:g}s."
        )

    def down(self):
        """Stop Phoenix while intentionally preserving its named data volume."""
        self._docker_ready()
        result = self._run(self._compose_command("down"))
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ObservabilityError(
                "Failed to stop Phoenix." + (f"\n{detail}" if detail else "")
            )

    def open(self) -> bool:
        self.up()
        return bool(webbrowser.open(self.config.ui_url))

    def create_trace_sink(self, session_id: str | None = None):
        self._ensure_local_otlp_bypasses_proxy()
        return OpenTelemetryTraceSink(
            endpoint=self.config.otlp_endpoint,
            project_name=self.config.project_name,
            content_policy=self.config.content_policy,
            session_id=session_id,
        )

    def _ensure_local_otlp_bypasses_proxy(self):
        parsed = urlparse(self.config.otlp_endpoint)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return
        required = ["127.0.0.1", "localhost", "::1"]
        for name in ("NO_PROXY", "no_proxy"):
            existing = [
                item.strip() for item in os.getenv(name, "").split(",")
                if item.strip()
            ]
            os.environ[name] = ",".join(dict.fromkeys(existing + required))
