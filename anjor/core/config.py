"""AnjorConfig — typed configuration via Pydantic BaseSettings.

Sources (in priority order):
  1. Init kwargs
  2. Environment variables (prefix ANJOR_)
  3. .anjor.toml in CWD or ~/.anjor/config.toml
  4. Hardcoded defaults

No secrets are logged or stored anywhere in this module.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


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

    # Network ports
    proxy_port: int = Field(default=7842, ge=1, le=65535)
    collector_port: int = Field(default=7843, ge=1, le=65535)

    # Storage
    db_path: str = "anjor.db"

    # Logging
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Payload limits
    max_payload_size_kb: int = Field(default=512, ge=1)

    # Batch writer
    batch_size: int = Field(default=100, ge=1)
    batch_interval_ms: int = Field(default=500, ge=1)

    # Sanitisation config (nested)
    sanitise: SanitiseConfig = Field(default_factory=SanitiseConfig)

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
