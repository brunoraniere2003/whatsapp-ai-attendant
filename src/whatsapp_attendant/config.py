"""Settings: a strict TOML file for tunables, environment variables for secrets.

Unknown keys and out-of-range values stop the service at startup with a message that names the
key (RQ-19). Secrets never live in the file (RQ-21): see `Secrets.from_env`.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_ENV = "ATTENDANT_CONFIG"


class ConfigError(ValueError):
    """The configuration file is missing, malformed or has invalid values."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EngineSettings(_Strict):
    confidence_threshold: float = Field(0.16, ge=0.05, le=0.95)
    switch_threshold: float = Field(0.45, ge=0.05, le=0.95)
    char_ngram_weight: float = Field(0.5, gt=0.0, le=1.0)


class DialogueSettings(_Strict):
    max_failed_turns: int = Field(2, ge=1, le=5)
    session_ttl_seconds: int = Field(1800, ge=60, le=86_400)
    max_sessions: int = Field(10_000, ge=10, le=1_000_000)
    learning_queue_size: int = Field(5_000, ge=10, le=1_000_000)


class LLMSettings(_Strict):
    model: str = Field("claude-opus-5-5", min_length=1)
    effort: Literal["low", "medium", "high"] = "low"
    min_confidence: float = Field(0.6, ge=0.0, le=1.0)
    max_tokens: int = Field(1024, ge=64, le=8192)
    # Inline budget: the call runs while the webhook request waits (RQ-34, ADR-006).
    timeout_seconds: float = Field(3.0, gt=0.0, le=5.0)
    max_retries: int = Field(1, ge=0, le=1)
    server_fallbacks: bool = True


class WhatsAppSettings(_Strict):
    graph_api_version: str = Field("v23.0", pattern=r"^v\d+\.\d+$")
    send_timeout_seconds: float = Field(10.0, gt=0.0, le=60.0)
    send_max_attempts: int = Field(3, ge=1, le=6)
    send_backoff_seconds: float = Field(0.5, ge=0.0, le=10.0)
    idempotency_ttl_seconds: int = Field(86_400, ge=60, le=7 * 86_400)
    idempotency_max_ids: int = Field(50_000, ge=100, le=5_000_000)
    # Failed attempts before a message is dead-lettered instead of redelivered (RQ-5).
    max_processing_attempts: int = Field(3, ge=1, le=10)
    # Largest webhook body read; larger ones get 413 before the signature check (RQ-33).
    max_body_bytes: int = Field(1_048_576, ge=1024, le=10_485_760)
    # Accept events without X-Hub-Signature-256 when no app secret is set. Local tests only.
    allow_unsigned: bool = False


class LoggingSettings(_Strict):
    file: str = Field("logs/attendant.log", min_length=1)
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_bytes: int = Field(5_000_000, ge=10_000, le=1_000_000_000)
    backup_count: int = Field(5, ge=1, le=50)


class DemoSettings(_Strict):
    enabled: bool = False  # /console and /dashboard; keep off in production


class Settings(_Strict):
    """Every tunable of the service. `config.example.toml` documents the defaults."""

    knowledge_base: str = ""  # empty: the bundled pt-BR knowledge base
    engine: EngineSettings = EngineSettings()
    dialogue: DialogueSettings = DialogueSettings()
    llm: LLMSettings = LLMSettings()
    whatsapp: WhatsAppSettings = WhatsAppSettings()
    logging: LoggingSettings = LoggingSettings()
    demo: DemoSettings = DemoSettings()


def _describe(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"])
        lines.append(f"{key}: {item['msg']}")
    return "; ".join(lines)


def parse_settings(data: dict) -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_describe(exc)}") from exc


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from `path`, from $ATTENDANT_CONFIG, or return the defaults."""
    chosen = path or os.environ.get(CONFIG_ENV)
    if not chosen:
        return Settings()
    file = Path(chosen)
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {file}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"configuration file is not valid TOML: {file}: {exc}") from exc
    return parse_settings(data)


@dataclass(frozen=True)
class Secrets:
    """Credentials read only from the environment, never from the config file."""

    verify_token: str | None = field(default=None, repr=False)
    access_token: str | None = field(default=None, repr=False)
    phone_number_id: str | None = field(default=None, repr=False)
    app_secret: str | None = field(default=None, repr=False)
    llm_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Secrets:
        source = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = source.get(name, "").strip()
            return value or None

        return cls(
            verify_token=get("WA_VERIFY_TOKEN"),
            access_token=get("WA_ACCESS_TOKEN"),
            phone_number_id=get("WA_PHONE_NUMBER_ID"),
            app_secret=get("WA_APP_SECRET"),
            llm_api_key=get("ANTHROPIC_API_KEY"),
        )
