import json

import pytest
from conftest import read_log
from fastapi.testclient import TestClient
from test_whatsapp import event, text

from whatsapp_attendant.api import create_app
from whatsapp_attendant.config import DemoSettings, Secrets
from whatsapp_attendant.nlu import Prediction
from whatsapp_attendant.whatsapp import (
    CloudApiSender,
    RecordingSender,
    SendError,
    signature_for,
)

PHONE = "5511999990005"


def make(settings, sender=None, **secrets):
    sender = sender or RecordingSender()
    app = create_app(settings, Secrets(verify_token="secret", **secrets), sender=sender)
    return TestClient(app), sender


def post(client, payload, secret=None):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if secret:
        headers["x-hub-signature-256"] = signature_for(secret, body)
    return client.post("/webhook", content=body, headers=headers)


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
    client, sender = make(settings, app_secret="app-secret")
    payload = event(text(PHONE, "wamid.s1", "bom dia"))
    assert post(client, payload, secret="app-secret").status_code == 200
    assert post(client, event(text(PHONE, "wamid.s2", "oi")), secret="other").status_code == 401
    assert post(client, event(text(PHONE, "wamid.s3", "oi"))).status_code == 401
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
    bad = client.post(
        "/webhook", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert bad.status_code == 400
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


class BrokenProvider:
    def classify(self, text: str) -> Prediction:
        return Prediction("not_understood", 0.0)


def test_ca_11_health_reports_ok_and_failure(settings):
    client, _ = make(settings)
    body = client.get("/health").json()
    assert body["status"] == "ok" and all(body["checks"].values())
    broken = TestClient(create_app(settings, Secrets(), provider=BrokenProvider()))
    r = broken.get("/health")
    assert r.status_code == 503 and r.json()["checks"]["classifier_self_test"] is False


def test_cloud_sender_is_chosen_when_credentials_exist(settings):
    app = create_app(settings, Secrets(access_token="t", phone_number_id="p"))
    assert isinstance(app.state.rt.sender, CloudApiSender)
    assert isinstance(create_app(settings, Secrets()).state.rt.sender, RecordingSender)


def test_ca_13_demo_ui_is_off_by_default(settings):
    client, _ = make(settings)
    assert client.get("/console").status_code == 404
    assert client.get("/dashboard").status_code == 404


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
