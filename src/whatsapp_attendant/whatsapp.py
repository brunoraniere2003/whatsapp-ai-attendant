"""WhatsApp Cloud API adapter: event parsing, signature check and outbound senders."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import WhatsAppSettings
from .logs import log_event, mask_phone

GRAPH_URL = "https://graph.facebook.com/{version}/{phone_number_id}/messages"
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class InboundMessage:
    phone: str
    message_id: str
    kind: str
    text: str | None


def _text_of(message: dict[str, Any]) -> str | None:
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body")
    if kind == "interactive":  # reply buttons and list pickers
        inner = message.get("interactive") or {}
        choice = inner.get("button_reply") or inner.get("list_reply") or {}
        return choice.get("title")
    if kind == "button":  # quick reply of a template
        return (message.get("button") or {}).get("text")
    return None


def parse_messages(payload: Any) -> list[InboundMessage]:
    """Inbound messages of a webhook payload; status updates and malformed parts are skipped."""
    if not isinstance(payload, dict):
        return []
    found: list[InboundMessage] = []
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                phone, message_id = message.get("from"), message.get("id")
                if not phone or not message_id:
                    continue
                text = _text_of(message)
                kind = "text" if text is not None else str(message.get("type") or "unknown")
                found.append(InboundMessage(str(phone), str(message_id), kind, text))
    return found


def signature_for(app_secret: str, body: bytes) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of the X-Hub-Signature-256 header (RQ-3)."""
    if not header:
        return False
    return hmac.compare_digest(signature_for(app_secret, body), header.strip())


class SendError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Sender(Protocol):
    def send_text(self, phone: str, text: str) -> None: ...


class RecordingSender:
    """Keeps the replies in memory. Used by the demo, the simulation and the tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_text(self, phone: str, text: str) -> None:
        self.sent.append((phone, text))


class CloudApiSender:
    """Sends text through the Graph API, retrying only transient failures (RQ-25)."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        settings: WhatsAppSettings | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or WhatsAppSettings()
        self.url = GRAPH_URL.format(
            version=self.settings.graph_api_version, phone_number_id=phone_number_id
        )
        self.client = client or httpx.Client(timeout=self.settings.send_timeout_seconds)
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.sleep = sleep

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after", "")
            if retry_after.isdigit():
                return min(float(retry_after), 30.0)
        return self.settings.send_backoff_seconds * (2 ** (attempt - 1))

    def send_text(self, phone: str, text: str) -> None:
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        attempts = self.settings.send_max_attempts
        for attempt in range(1, attempts + 1):
            response: httpx.Response | None = None
            try:
                response = self.client.post(self.url, json=body, headers=self.headers)
            except httpx.TransportError as exc:
                problem, status = type(exc).__name__, None
            else:
                if response.status_code < 300:
                    return
                problem, status = f"HTTP {response.status_code}", response.status_code
                if status not in TRANSIENT_STATUS:
                    log_event(
                        "send.failed",
                        logging.ERROR,
                        phone=mask_phone(phone),
                        status=status,
                        attempt=attempt,
                        retryable=False,
                    )
                    raise SendError(f"Cloud API refused the message: {problem}", status)
            if attempt == attempts:
                log_event(
                    "send.failed",
                    logging.ERROR,
                    phone=mask_phone(phone),
                    status=status,
                    attempt=attempt,
                    retryable=True,
                )
                raise SendError(
                    f"Cloud API send failed after {attempts} attempts: {problem}", status
                )
            delay = self._backoff(attempt, response)
            log_event("send.retry", logging.WARNING, status=status, attempt=attempt, delay=delay)
            self.sleep(delay)
