import tomllib

import pytest
from conftest import ROOT
from pydantic import BaseModel

from whatsapp_attendant.config import (
    CONFIG_ENV,
    ConfigError,
    Secrets,
    Settings,
    load_settings,
    parse_settings,
)


def test_ca_10_example_config_equals_the_defaults():
    data = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert parse_settings(data) == Settings()


def test_ca_10_unknown_key_is_an_error_that_names_it():
    with pytest.raises(ConfigError, match=r"engine\.treshold"):
        parse_settings({"engine": {"treshold": 0.3}})


def test_ca_10_out_of_range_value_is_an_error_that_names_it():
    with pytest.raises(ConfigError, match=r"engine\.confidence_threshold"):
        parse_settings({"engine": {"confidence_threshold": 2.0}})


def test_ca_10_secrets_are_not_settings():
    def names(model: BaseModel) -> set[str]:
        found = set()
        for name in type(model).model_fields:
            found.add(name)
            value = getattr(model, name)
            if isinstance(value, BaseModel):
                found |= names(value)
        return found

    secret_fields = set(Secrets.__dataclass_fields__)
    words = ("secret", "api_key", "access_token", "verify_token", "password")
    settings_fields = names(Settings())
    assert not settings_fields & secret_fields
    assert not {n for n in settings_fields if any(w in n for w in words)}


def test_load_settings_from_file_env_and_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert load_settings() == Settings()
    file = tmp_path / "c.toml"
    file.write_text("[dialogue]\nmax_failed_turns = 3\n", encoding="utf-8")
    assert load_settings(file).dialogue.max_failed_turns == 3
    monkeypatch.setenv(CONFIG_ENV, str(file))
    assert load_settings().dialogue.max_failed_turns == 3


def test_load_settings_reports_missing_and_malformed_files(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("engine = [", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_settings(bad)


def test_secrets_come_from_the_environment():
    env = {"WA_VERIFY_TOKEN": " t ", "WA_APP_SECRET": "", "ANTHROPIC_API_KEY": "k"}
    s = Secrets.from_env(env)
    assert (s.verify_token, s.app_secret, s.llm_api_key, s.access_token) == ("t", None, "k", None)
    assert isinstance(Secrets.from_env(), Secrets)


def test_ca_10_secrets_never_show_in_a_repr():
    keys = Secrets(
        verify_token="vt-123",
        access_token="at-456",
        phone_number_id="pn-789",
        app_secret="as-000",
        llm_api_key="sk-111",
    )
    shown = repr(keys) + str(keys)
    assert not any(v in shown for v in ("vt-123", "at-456", "as-000", "sk-111"))


def test_ca_16_llm_budget_is_short_by_default_and_bounded():
    llm = Settings().llm
    assert (llm.timeout_seconds, llm.max_retries) == (3.0, 1)
    with pytest.raises(ConfigError, match=r"llm\.timeout_seconds"):
        parse_settings({"llm": {"timeout_seconds": 6.0}})
    with pytest.raises(ConfigError, match=r"llm\.max_retries"):
        parse_settings({"llm": {"max_retries": 2}})


def test_ca_15_webhook_limits_are_validated():
    whatsapp = Settings().whatsapp
    assert whatsapp.allow_unsigned is False and whatsapp.max_body_bytes == 1_048_576
    assert whatsapp.max_processing_attempts == 3
    with pytest.raises(ConfigError, match=r"whatsapp\.max_body_bytes"):
        parse_settings({"whatsapp": {"max_body_bytes": 100}})
