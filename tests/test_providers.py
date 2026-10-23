import sys

import pytest
from conftest import FakeLLMClient, FakeMessages, read_log

from whatsapp_attendant.config import EngineSettings, LLMSettings, Secrets
from whatsapp_attendant.logs import setup_logging
from whatsapp_attendant.providers import (
    SERVER_FALLBACK_BETA,
    LLMFallbackProvider,
    LocalProvider,
    build_provider,
)

LOW = "vocês vendem bicicleta?"  # rejected by the local engine


def _provider(kb, messages: FakeMessages, **llm) -> LLMFallbackProvider:
    return LLMFallbackProvider(LocalProvider(kb), kb, LLMSettings(**llm), FakeLLMClient(messages))


def test_ca_6_without_key_the_provider_is_local_only(kb):
    provider = build_provider(kb, EngineSettings(), LLMSettings(), Secrets())
    assert isinstance(provider, LocalProvider)


def test_ca_6_with_key_the_llm_layer_is_built_without_any_call(kb):
    provider = build_provider(kb, EngineSettings(), LLMSettings(), Secrets(llm_api_key="test"))
    assert isinstance(provider, LLMFallbackProvider)


def test_ca_6_missing_sdk_falls_back_to_local(kb, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    provider = build_provider(kb, EngineSettings(), LLMSettings(), Secrets(llm_api_key="test"))
    assert isinstance(provider, LocalProvider)


def test_ca_6_llm_resolves_low_confidence_message(kb):
    messages = FakeMessages({"intent": "business_hours", "confidence": 0.91})
    p = _provider(kb, messages).classify(LOW)
    assert (p.intent, p.source, p.confidence) == ("business_hours", "llm", 0.91)
    call = messages.calls[0]
    assert call["betas"] == [SERVER_FALLBACK_BETA] and call["fallbacks"] == "default"
    schema = call["output_config"]["format"]["schema"]
    assert set(schema["properties"]["intent"]["enum"]) == {*kb.intent_names, "none"}
    assert call["messages"] == [{"role": "user", "content": LOW}]


def test_ca_6_without_server_fallbacks_uses_plain_messages(kb):
    messages = FakeMessages({"intent": "greeting", "confidence": 0.8})
    _provider(kb, messages, server_fallbacks=False).classify(LOW)
    assert "betas" not in messages.calls[0]


def test_ca_6_confident_local_result_never_calls_the_llm(kb):
    messages = FakeMessages({"intent": "goodbye", "confidence": 1})
    assert _provider(kb, messages).classify("quero cancelar meu pedido").intent == "cancel_order"
    assert _provider(kb, messages).classify("   ").intent == "not_understood"
    assert messages.calls == []


@pytest.mark.parametrize(
    "answer",
    [{"intent": "none", "confidence": 0.99}, {"intent": "greeting", "confidence": 0.2}],
)
def test_ca_6_unknown_or_unsure_llm_answer_keeps_local(kb, answer):
    assert _provider(kb, FakeMessages(answer)).classify(LOW).intent == "not_understood"


@pytest.mark.parametrize(
    "messages",
    [
        FakeMessages({"intent": "greeting", "confidence": 1}, stop_reason="refusal"),
        FakeMessages(error=TimeoutError("slow")),
        FakeMessages("not json"),
    ],
)
def test_ca_6_failures_keep_local_and_log_llm_error(kb, settings, messages):
    setup_logging(settings.logging)
    assert _provider(kb, messages).classify(LOW).intent == "not_understood"
    assert any(e["event"] == "llm.error" for e in read_log(settings))


@pytest.mark.parametrize("confidence", ["NaN", "Infinity"])
def test_ca_6_a_non_finite_llm_confidence_keeps_local(kb, settings, confidence):
    setup_logging(settings.logging)
    answer = f'{{"intent": "greeting", "confidence": {confidence}}}'
    assert _provider(kb, FakeMessages(answer)).classify(LOW).intent == "not_understood"
    assert any(e["event"] == "llm.error" for e in read_log(settings))


def test_ca_6_a_message_without_content_words_never_reaches_the_llm(kb):
    messages = FakeMessages({"intent": "greeting", "confidence": 0.99})
    provider = _provider(kb, messages)
    for text in ("o", "é o", "!!!", " , "):
        assert provider.classify(text).intent == "not_understood"
    assert messages.calls == []


def test_ca_16_the_llm_client_gets_the_inline_budget(kb, monkeypatch):
    import anthropic

    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return FakeLLMClient(FakeMessages())

    monkeypatch.setattr(anthropic, "Anthropic", fake_client)
    build_provider(kb, EngineSettings(), LLMSettings(), Secrets(llm_api_key="test"))
    assert (captured["timeout"], captured["max_retries"]) == (3.0, 1)
