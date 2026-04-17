"""AnjorConfig — typed configuration via Pydantic BaseSettings.

Sources (in priority order):
  1. Init kwargs
  2. Environment variables (prefix ANJOR_)
  3. .anjor.toml in CWD or ~/.anjor/config.toml
  4. Hardcoded defaults

No secrets are logged or stored anywhere in this module.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

_log = logging.getLogger(__name__)


class ExportConfig(BaseModel):
    """OTLP export settings from [export] in .anjor.toml."""

    model_config = {"frozen": True}

    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = Field(default_factory=dict)


class AlertConfig(BaseModel):
    """A single alert condition from [[alerts]] in .anjor.toml."""

    name: str
    condition: str  # e.g. "failure_rate > 0.20" or "context_utilisation > 0.80"
    window_calls: int = Field(default=10, ge=1)  # rolling window for rate/latency metrics
    webhook: str  # URL to POST alert payload to


class SanitiseConfig(BaseSettings):
    """Rules for stripping sensitive keys from payloads before storage."""

    model_config = {"env_prefix": "ANJOR_SANITISE_", "frozen": True}

    # fnmatch-style patterns matched case-insensitively against key names
    strip_patterns: list[str] = Field(
        default=[
            "*api_key*",
            "*secret*",
            "*password*",
            "*token*",
            "*auth*",
            "*bearer*",
        ]
    )


def _load_toml_config() -> dict[str, Any]:
    """Load config from .anjor.toml (CWD) or ~/.anjor/config.toml."""
    candidates = [
        Path.cwd() / ".anjor.toml",
        Path.home() / ".anjor" / "config.toml",
    ]
    for path in candidates:
        if path.exists():
            with path.open("rb") as f:
                return tomllib.load(f)
    return {}


class TomlConfigSource(PydanticBaseSettingsSource):
    """Pydantic settings source that reads from TOML files."""

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:  # pragma: no cover
        data = _load_toml_config()
        value = data.get(field_name)
        return value, field_name, value is not None

    def __call__(self) -> dict[str, Any]:
        return _load_toml_config()


class AnjorConfig(BaseSettings):
    """Central configuration for Anjor.

    All fields can be set via env vars with the ANJOR_ prefix.
    """

    # DECISION: frozen=True so config can be passed around safely without callers
    # mutating it mid-flight — config is established at startup, not modified at runtime.
    model_config = {"env_prefix": "ANJOR_", "frozen": True}

    # Mode: patch (in-process httpx monkey-patch) or proxy (mitmproxy)
    mode: str = Field(default="patch", pattern="^(patch|proxy)$")

    # Network
    host: str = Field(default="127.0.0.1")
    proxy_port: int = Field(default=7842, ge=1, le=65535)
    collector_port: int = Field(default=7843, ge=1, le=65535)

    # Storage
    storage_backend: str = Field(default="sqlite", pattern="^(sqlite|postgres|clickhouse)$")
    storage_url: str | None = None  # required for postgres/clickhouse; unused by sqlite
    db_path: str = str(Path.home() / ".anjor" / "anjor.db")  # sqlite only

    # Logging
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Payload limits
    max_payload_size_kb: int = Field(default=512, ge=1)

    # Batch writer
    batch_size: int = Field(default=100, ge=1)
    batch_interval_ms: int = Field(default=500, ge=1)

    # Terminal summary printed at process exit (disable with ANJOR_SHOW_SUMMARY=false)
    show_summary: bool = Field(default=True)

    # Conversation capture: on by default. User and assistant text turns are captured
    # as MessageEvents (first 500 chars only), stored locally only.
    # Disable with ANJOR_CAPTURE_MESSAGES=false, capture_messages=false in .anjor.toml,
    # or --no-capture-messages on the CLI.
    capture_messages: bool = Field(default=True)

    # Rate limiting on POST /events (token bucket per source IP)
    # Defaults are intentionally generous — local use never hits them.
    # Set rate_limit_rps=0 to disable entirely.
    rate_limit_rps: float = Field(default=500, ge=0)
    rate_limit_burst: int = Field(default=1000, ge=1)

    # Sanitisation config (nested)
    sanitise: SanitiseConfig = Field(default_factory=SanitiseConfig)

    # Alert conditions — configured via [[alerts]] in .anjor.toml
    alerts: list[AlertConfig] = Field(default_factory=list)

    # OTLP export — configured via [export] in .anjor.toml
    export: ExportConfig = Field(default_factory=ExportConfig)

    @field_validator("host")
    @classmethod
    def warn_if_public_bind(cls, v: str) -> str:
        if v == "0.0.0.0":  # noqa: S104
            _log.warning(
                "Anjor collector is binding to 0.0.0.0 — it will be reachable "
                "on all network interfaces. Do not expose this to untrusted networks."
            )
        return v

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        if v not in ("patch", "proxy"):
            raise ValueError(f"mode must be 'patch' or 'proxy', got {v!r}")
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # DECISION: explicit signature matches supertype exactly so mypy strict is happy.
        # We omit dotenv_settings and file_secret_settings — config comes from env + TOML.
        return (
            init_settings,
            env_settings,
            TomlConfigSource(settings_cls),
        )
