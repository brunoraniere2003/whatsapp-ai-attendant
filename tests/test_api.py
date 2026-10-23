import asyncio
import base64
import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import read_log
from fastapi.testclient import TestClient
from test_whatsapp import event, text

from whatsapp_attendant.api import create_app
from whatsapp_attendant.config import ConfigError, DemoSettings, Secrets, WhatsAppSettings
from whatsapp_attendant.nlu import Prediction
from whatsapp_attendant.providers import LocalProvider
from whatsapp_attendant.whatsapp import (
    CloudApiSender,
    RecordingSender,
    SendError,
    signature_for,
)

PHONE = "5511999990005"
APP_SECRET = "app-secret"
# A real-shaped Cloud API message id: the base64 part encodes the sender's phone, 16505076520.
WAMID = "wamid.HBgLMTY1MDUwNzY1MjAVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA="
WAMID_PHONE = "16505076520"


def make(settings, sender=None, provider=None, app_secret=APP_SECRET, **secrets):
    sender = sender or RecordingSender()
    keys = Secrets(verify_token="secret", app_secret=app_secret, **secrets)
    app = create_app(settings, keys, sender=sender, provider=provider)
    return TestClient(app), sender


def post(client, payload, secret=APP_SECRET):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if secret:
        headers["x-hub-signature-256"] = signature_for(secret, body)
    return client.post("/webhook", content=body, headers=headers)


def with_whatsapp(settings, **values):
    return settings.model_copy(update={"whatsapp": WhatsAppSettings(**values)})


def test_ca_1_verification_echoes_the_challenge(settings):
    client, _ = make(settings)
    params = {"hub.mode": "subscribe", "hub.verify_token": "secret", "hub.challenge": "42"}
    r = client.get("/webhook", params=params)
    assert r.status_code == 200 and r.text == "42"
    params["hub.verify_token"] = "wrong"
    assert client.get("/webhook", params=params).status_code == 403


def test_ca_1_verification_fails_closed_without_a_token(settings):
    client = TestClient(create_app(settings, Secrets(), sender=RecordingSender()))
    params = {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "42"}
    assert client.get("/webhook", params=params).status_code == 403


def test_ca_2_signed_events_only(settings):
    client, sender = make(settings)
    payload = event(text(PHONE, "wamid.s1", "bom dia"))
    assert post(client, payload).status_code == 200
    assert post(client, event(text(PHONE, "wamid.s2", "oi")), secret="other").status_code == 401
    assert post(client, event(text(PHONE, "wamid.s3", "oi")), secret=None).status_code == 401
    assert len(sender.sent) == 1
    assert client.get("/metrics").json()["invalid_signatures"] == 2


def test_ca_3_reply_and_idempotency(settings):
    client, sender = make(settings)
    payload = event(text(PHONE, "wamid.1", "bom dia"))
    assert post(client, payload).json() == {"status": "ok"}
    post(client, payload)  # Meta redelivers
    assert len(sender.sent) == 1 and sender.sent[0][1].startswith("Olá, aqui é o atendimento")
    m = client.get("/metrics").json()
    assert (m["received"], m["duplicates"], m["replied"], m["sessions"]) == (1, 1, 1, 1)


def test_ca_4_media_status_and_invalid_body(settings, kb):
    client, sender = make(settings)
    image = {"from": PHONE, "id": "wamid.img", "type": "image", "image": {"id": "m"}}
    post(client, event(image))
    assert sender.sent == [(PHONE, kb.unsupported_reply)]
    assert post(client, event(statuses=[{"id": "wamid.1", "status": "read"}])).status_code == 200
    assert len(sender.sent) == 1
    assert post(client, b"{not json").status_code == 400
    assert client.get("/metrics").json()["unsupported"] == 1


def test_ca_11_logs_are_json_in_the_file_and_stdout_stays_clean(settings, capsys):
    client, _ = make(settings)
    post(client, event(text(PHONE, "wamid.log", "quero falar com uma pessoa")))
    entries = read_log(settings)
    events = {e["event"] for e in entries}
    assert {"message.received", "message.replied", "handoff"} <= events
    assert all(e.get("phone", "5511*******05") == "5511*******05" for e in entries)
    assert PHONE not in json.dumps(entries)
    assert capsys.readouterr().out == ""


def test_ca_11_counters_follow_handoffs_and_failures(settings):
    client, _ = make(settings)
    post(client, event(text("1111111111", "w1", "quero falar com uma pessoa")))
    post(client, event(text("2222222222", "w2", "xyz abc")))
    post(client, event(text("2222222222", "w3", "qwerty zzz")))
    m = client.get("/metrics").json()
    assert m["handoff_customer_request"] == 1 and m["handoff_repeated_failures"] == 1
    assert m["not_understood"] == 2 and m["learning_queue"] == 2
    assert m["latency_p95_ms"] >= m["latency_p50_ms"] >= 0


class FailingSender:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def send_text(self, phone: str, text: str) -> None:
        raise self.error


@pytest.mark.parametrize("error", [SendError("refused", 401), RuntimeError("bug")])
def test_ca_11_send_failures_are_counted_not_raised(settings, error):
    client, _ = make(settings, sender=FailingSender(error))
    assert post(client, event(text(PHONE, "wamid.f", "bom dia"))).status_code == 200
    assert client.get("/metrics").json()["send_failures"] == 1
    if type(error) is RuntimeError:  # an unexpected sender bug is logged with its traceback
        failed = [e for e in read_log(settings) if e["event"] == "send.failed"]
        assert failed and "RuntimeError: bug" in failed[0]["exc"]


class BrokenProvider:
    def classify(self, text: str) -> Prediction:
        return Prediction("not_understood", 0.0)


def test_ca_11_health_reports_ok_and_failure(settings):
    client, _ = make(settings)
    body = client.get("/health").json()
    assert body["status"] == "ok" and all(body["checks"].values())
    assert body["checks"]["signature_check"] is True
    broken, _ = make(settings, provider=BrokenProvider())
    r = broken.get("/health")
    assert r.status_code == 503 and r.json()["checks"]["classifier_self_test"] is False


def test_cloud_sender_is_chosen_when_credentials_exist(settings):
    keys = Secrets(access_token="t", phone_number_id="p", app_secret=APP_SECRET)
    app = create_app(settings, keys)
    assert isinstance(app.state.rt.sender, CloudApiSender)
    assert isinstance(create_app(settings, Secrets()).state.rt.sender, RecordingSender)


# CA-13: demo UI ---------------------------------------------------------------------------------


def test_ca_13_demo_ui_is_off_by_default(settings):
    client, _ = make(settings)
    assert client.get("/console").status_code == 404
    assert client.get("/dashboard").status_code == 404


def test_ca_13_api_docs_exist_only_in_demo_mode(settings):
    client, _ = make(settings)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
    demo, _ = make(settings.model_copy(update={"demo": DemoSettings(enabled=True)}))
    assert demo.get("/openapi.json").status_code == 200


def test_ca_13_demo_ui_serves_console_and_dashboard(settings):
    demo = settings.model_copy(update={"demo": DemoSettings(enabled=True)})
    client, sender = make(demo)
    page = client.get("/console", params={"scenario": "two-failures"})
    assert page.status_code == 200 and "Two misunderstandings" in page.text
    assert "vocês vendem bicicleta?" in page.text
    assert client.get("/console", params={"scenario": "unknown"}).status_code == 200
    turn = client.post("/console/api/message", json={"session": "abc", "text": "perdi o boleto"})
    assert turn.json()["intent"] == "invoice_copy" and turn.json()["action"] == "ask_slot"
    bad = client.post("/console/api/message", json={"session": "a b", "text": "x"})
    assert bad.status_code == 422
    overview = client.get("/dashboard")
    assert overview.status_code == 200 and "Full report" in overview.text
    full = client.get("/dashboard", params={"lang": "pt", "view": "full"})
    assert "Case demonstrativo com dados fictícios." in full.text
    assert client.get("/dashboard", params={"lang": "fr"}).status_code == 404
    assert sender.sent == []  # the sandbox never sends


# CA-15: webhook hardening -----------------------------------------------------------------------


def test_ca_15_without_an_app_secret_the_webhook_fails_closed(settings):
    client, sender = make(settings, app_secret=None)
    r = post(client, event(text(PHONE, "wamid.u1", "bom dia")), secret=None)
    assert r.status_code == 503 and sender.sent == []
    health = client.get("/health")
    assert health.status_code == 503 and health.json()["checks"]["signature_check"] is False
    assert any(e["event"] == "signature.unconfigured" for e in read_log(settings))


def test_ca_15_allow_unsigned_accepts_unsigned_events_for_local_tests(settings):
    client, sender = make(with_whatsapp(settings, allow_unsigned=True), app_secret=None)
    assert post(client, event(text(PHONE, "wamid.u2", "bom dia")), secret=None).status_code == 200
    assert len(sender.sent) == 1
    assert client.get("/health").json()["checks"]["signature_check"] is True


def test_ca_15_an_access_token_without_an_app_secret_refuses_to_start(settings):
    with pytest.raises(ConfigError, match="WA_APP_SECRET"):
        create_app(settings, Secrets(access_token="t", phone_number_id="p"))


def test_ca_15_a_non_ascii_signature_header_is_401_not_500(settings):
    client, sender = make(settings)
    body = json.dumps(event(text(PHONE, "wamid.na", "bom dia"))).encode()
    headers = {
        "content-type": "application/json",
        "x-hub-signature-256": "sha256=\xe9".encode("latin-1"),
    }
    r = client.post("/webhook", content=body, headers=headers)
    assert r.status_code == 401 and sender.sent == []


def test_ca_15_bodies_above_the_limit_get_413_before_the_signature_check(settings):
    client, sender = make(with_whatsapp(settings, max_body_bytes=2048))
    big = json.dumps(event(text(PHONE, "wamid.big", "x" * 4000))).encode()
    assert post(client, big).status_code == 413

    def chunks():  # no Content-Length: the server must stop reading at the limit
        for _ in range(8):
            yield b" " * 1024

    streamed = client.post("/webhook", content=chunks(), headers={"x-hub-signature-256": "x"})
    assert streamed.status_code == 413
    small = event(text(PHONE, "wamid.ok", "bom dia"))
    assert post(client, small).status_code == 200 and len(sender.sent) == 1
    m = client.get("/metrics").json()
    assert m["oversized_bodies"] == 2 and m["invalid_signatures"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"entry": {"a": 1}},
        {"entry": [{"changes": [{"value": []}]}]},
        {"entry": ["x", {"changes": "y"}]},
        event({"from": PHONE, "id": "wamid.m1", "type": "text", "text": "oi"}),
        event({"from": PHONE, "id": "wamid.m2", "type": "text", "text": {"body": 42}}),
        event({"from": 5511, "id": "wamid.m3", "type": "text", "text": {"body": "oi"}}),
        event({"from": PHONE, "id": ["x"], "type": "text", "text": {"body": "oi"}}),
        event({"from": PHONE, "id": "wamid.m4", "type": "interactive", "interactive": "x"}),
        [1, 2, 3],
    ],
)
def test_ca_15_malformed_parts_are_skipped_never_500(settings, payload):
    client, sender = make(settings)
    r = post(client, payload)
    assert r.status_code == 200 and sender.sent == []


def test_ca_15_json_nested_too_deep_is_400(settings):
    client, _ = make(settings)
    assert post(client, b"[" * 100_000 + b"]" * 100_000).status_code == 400


def test_ca_15_logs_never_carry_the_message_id_or_the_phone_it_encodes(settings):
    assert WAMID_PHONE.encode() in base64.b64decode(WAMID.removeprefix("wamid."))
    client, _ = make(settings)
    payload = event(text(WAMID_PHONE, WAMID, "bom dia"))
    post(client, payload)
    post(client, payload)  # duplicate, logged too
    raw = Path(settings.logging.file).read_text(encoding="utf-8")
    assert "message.received" in raw and "message.duplicate" in raw
    assert WAMID not in raw and WAMID.removeprefix("wamid.")[:20] not in raw
    assert WAMID_PHONE not in raw
    refs = {e["message_ref"] for e in read_log(settings) if "message_ref" in e}
    assert len(refs) == 1 and len(next(iter(refs))) == 16


@pytest.mark.parametrize("challenge", ["abc", "1" * 65, "<script>", ""])
def test_ca_15_challenge_must_be_1_to_64_digits(settings, challenge):
    client, _ = make(settings)
    params = {"hub.mode": "subscribe", "hub.verify_token": "secret", "hub.challenge": challenge}
    assert client.get("/webhook", params=params).status_code == 400


def test_ca_15_a_non_ascii_verify_token_is_403_not_500(settings):
    client, _ = make(settings)
    params = {"hub.mode": "subscribe", "hub.verify_token": "segrédo", "hub.challenge": "1"}
    assert client.get("/webhook", params=params).status_code == 403


# CA-16: non-blocking handling and idempotency after success -------------------------------------


class BlockingProvider:
    """Blocks inside classify until released, like a slow LLM call."""

    def __init__(self, kb) -> None:
        self.local = LocalProvider(kb)
        self.entered = threading.Event()
        self.release = threading.Event()

    def classify(self, text: str) -> Prediction:
        if "lento" in text:
            self.entered.set()
            self.release.wait(timeout=5)
        return self.local.classify(text)


def test_ca_16_a_slow_classification_does_not_block_metrics(settings, kb):
    provider = BlockingProvider(kb)
    app = create_app(
        settings, Secrets(app_secret=APP_SECRET), sender=RecordingSender(), provider=provider
    )
    body = json.dumps(event(text(PHONE, "wamid.slow", "pedido lento"))).encode()
    headers = {"x-hub-signature-256": signature_for(APP_SECRET, body)}

    async def scenario() -> tuple[float, float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            webhook = asyncio.create_task(ac.post("/webhook", content=body, headers=headers))
            while not provider.entered.is_set():
                await asyncio.sleep(0.01)
            start = time.perf_counter()
            metrics = await asyncio.wait_for(ac.get("/metrics"), timeout=4)
            served = time.perf_counter() - start
            assert metrics.status_code == 200 and not webhook.done()
            provider.release.set()
            assert (await webhook).status_code == 200
            return served, time.perf_counter() - start

    served, total = asyncio.run(scenario())
    assert served < 1.0 and served <= total


class FlakyProvider:
    """Raises for messages containing "boom" while `failures` is positive."""

    def __init__(self, kb, failures: int) -> None:
        self.local = LocalProvider(kb)
        self.failures = failures

    def classify(self, text: str) -> Prediction:
        if "boom" in text and self.failures > 0:
            self.failures -= 1
            raise RuntimeError("engine exploded")
        return self.local.classify(text)


def test_ca_16_a_failed_message_is_not_marked_and_the_others_are_answered(settings, kb):
    provider = FlakyProvider(kb, failures=1)
    client, sender = make(settings, provider=provider)
    payload = event(text("5511999990001", "wamid.a", "boom"), text(PHONE, "wamid.b", "bom dia"))
    first = post(client, payload)
    assert first.status_code == 500 and [p for p, _ in sender.sent] == [PHONE]
    failed = [e for e in read_log(settings) if e["event"] == "message.failed"]
    assert failed and "engine exploded" in failed[0]["exc"] and failed[0]["dead_letter"] is False
    second = post(client, payload)  # Meta redelivers the event
    assert second.status_code == 200 and len(sender.sent) == 2
    m = client.get("/metrics").json()
    assert (m["processing_errors"], m["duplicates"], m["dead_letters"]) == (1, 1, 0)


def test_ca_16_a_message_that_keeps_failing_is_dead_lettered(settings, kb):
    provider = FlakyProvider(kb, failures=10)
    client, sender = make(with_whatsapp(settings, max_processing_attempts=2), provider=provider)
    payload = event(text(PHONE, "wamid.poison", "boom"))
    assert post(client, payload).status_code == 500
    assert post(client, payload).status_code == 200  # second failure: given up
    assert post(client, payload).status_code == 200  # now a duplicate
    m = client.get("/metrics").json()
    assert (m["processing_errors"], m["dead_letters"], m["duplicates"]) == (2, 1, 1)
    assert sender.sent == []
    dead = [e for e in read_log(settings) if e["event"] == "message.failed" and e["dead_letter"]]
    assert len(dead) == 1


def test_ca_13_the_console_never_calls_the_llm_and_runs_the_scenarios_once(
    settings, kb, monkeypatch
):
    from conftest import FakeLLMClient, FakeMessages

    from whatsapp_attendant import demo as demo_ui
    from whatsapp_attendant.config import LLMSettings
    from whatsapp_attendant.providers import LLMFallbackProvider

    runs = []
    real = demo_ui.run_scenarios
    monkeypatch.setattr(demo_ui, "run_scenarios", lambda a: runs.append(1) or real(a))
    messages = FakeMessages({"intent": "business_hours", "confidence": 0.99})
    llm = LLMFallbackProvider(LocalProvider(kb), kb, LLMSettings(), FakeLLMClient(messages))
    client, _ = make(settings.model_copy(update={"demo": DemoSettings(enabled=True)}), provider=llm)
    for scenario in ("two-failures", "two-failures", "order-status", ""):
        assert client.get("/console", params={"scenario": scenario}).status_code == 200
    typed = client.post("/console/api/message", json={"session": "s", "text": "bicicleta?"})
    assert typed.json()["intent"] == "not_understood"
    assert messages.calls == [] and runs == [1]
    assert "LLM layer: on for the webhook, off in this console" in client.get("/console").text


def test_ca_13_the_dashboard_explains_a_configuration_it_cannot_evaluate(settings):
    from whatsapp_attendant.config import EngineSettings

    tuned = settings.model_copy(
        update={
            "demo": DemoSettings(enabled=True),
            "engine": EngineSettings(confidence_threshold=0.5),
        }
    )
    client, _ = make(tuned)
    r = client.get("/dashboard")
    assert r.status_code == 503 and "threshold" in r.json()["detail"]
