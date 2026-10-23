import httpx
import pytest
from conftest import read_log

from whatsapp_attendant.config import WhatsAppSettings
from whatsapp_attendant.logs import setup_logging
from whatsapp_attendant.whatsapp import (
    CloudApiSender,
    RecordingSender,
    SendError,
    parse_messages,
    signature_for,
    verify_signature,
)


def event(*messages: dict, statuses: list | None = None) -> dict:
    value: dict = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"}}
    if messages:
        value["messages"] = list(messages)
    if statuses:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
    }


def text(phone: str, message_id: str, body: str) -> dict:
    return {"from": phone, "id": message_id, "type": "text", "text": {"body": body}}


def test_parse_text_interactive_button_and_media():
    payload = event(
        text("1", "a", "oi"),
        {
            "from": "1",
            "id": "b",
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"title": "Status do pedido"}},
        },
        {"from": "1", "id": "c", "type": "button", "button": {"text": "Sim"}},
        {"from": "1", "id": "d", "type": "image", "image": {"id": "media"}},
        {"from": "1", "type": "text", "text": {"body": "sem id"}},
        "not a dict",
    )
    found = [(m.message_id, m.kind, m.text) for m in parse_messages(payload)]
    assert found == [
        ("a", "text", "oi"),
        ("b", "text", "Status do pedido"),
        ("c", "text", "Sim"),
        ("d", "image", None),
    ]


@pytest.mark.parametrize("payload", [None, [], {"entry": None}, event(statuses=[{"id": "x"}])])
def test_parse_ignores_statuses_and_malformed_payloads(payload):
    assert parse_messages(payload) == []


def test_signature_check_is_exact():
    body = b'{"a":1}'
    good = signature_for("app-secret", body)
    assert good.startswith("sha256=") and verify_signature("app-secret", body, good)
    assert not verify_signature("app-secret", body, "sha256=deadbeef")
    assert not verify_signature("app-secret", body + b" ", good)
    assert not verify_signature("app-secret", body, None)


def _sender(responses: list, sleeps: list[float], **settings) -> tuple[CloudApiSender, list]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = CloudApiSender(
        "token", "999", WhatsAppSettings(**settings), client=client, sleep=sleeps.append
    )
    return sender, calls


def test_ca_11_transient_errors_are_retried_with_backoff():
    sleeps: list[float] = []
    sender, calls = _sender([httpx.Response(503), httpx.Response(503), httpx.Response(200)], sleeps)
    sender.send_text("5511999990001", "olá")
    assert len(calls) == 3 and sleeps == [0.5, 1.0]
    assert calls[0].url.path == "/v23.0/999/messages"
    assert calls[0].headers["authorization"] == "Bearer token"
    assert b'"to":"5511999990001"' in calls[0].content


def test_ca_11_client_errors_are_not_retried_and_are_logged(settings):
    setup_logging(settings.logging)
    sleeps: list[float] = []
    sender, calls = _sender([httpx.Response(401)], sleeps)
    with pytest.raises(SendError) as info:
        sender.send_text("5511999990001", "olá")
    assert info.value.status == 401 and len(calls) == 1 and sleeps == []
    failed = [e for e in read_log(settings) if e["event"] == "send.failed"]
    assert failed and failed[0]["retryable"] is False and failed[0]["phone"] == "5511*******01"


def test_network_errors_and_retry_after_are_handled():
    sleeps: list[float] = []
    responses = [
        httpx.ConnectTimeout("slow"),
        httpx.Response(429, headers={"retry-after": "7"}),
        httpx.Response(200),
    ]
    sender, calls = _sender(responses, sleeps, send_max_attempts=3)
    sender.send_text("1", "x")
    assert len(calls) == 3 and sleeps == [0.5, 7.0]


def test_attempts_are_bounded():
    sleeps: list[float] = []
    sender, calls = _sender([httpx.Response(500)] * 2, sleeps, send_max_attempts=2)
    with pytest.raises(SendError, match="after 2 attempts"):
        sender.send_text("1", "x")
    assert len(calls) == 2


def test_recording_sender_and_default_client():
    rec = RecordingSender()
    rec.send_text("1", "oi")
    assert rec.sent == [("1", "oi")]
    assert isinstance(CloudApiSender("t", "p").client, httpx.Client)
