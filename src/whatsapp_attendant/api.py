"""FastAPI app: Cloud API webhook, health, metrics and the optional demo UI.

Run with `python -m whatsapp_attendant serve` (or `uvicorn --factory
whatsapp_attendant.api:create_app`). Building the app loads and validates the configuration and the
knowledge base, so a bad file stops the service at startup (RQ-19, RQ-20).

How an event is processed (ADR-006): refuse it without a signature setup (503), bound the body
(413), check the HMAC (401), parse it (400), then handle each message in a worker thread, marking
its id only after success. Replies go out after the answer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass, field
from secrets import token_bytes

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .config import ConfigError, Secrets, Settings, load_settings
from .dialogue import Action, Attendant, HandoffReason, Turn
from .knowledge import KnowledgeBase, load_knowledge_base
from .logs import log_event, mask_phone, setup_logging
from .metrics import Metrics
from .providers import IntentProvider, build_provider
from .store import MessageLedger
from .whatsapp import (
    CloudApiSender,
    InboundMessage,
    RecordingSender,
    Sender,
    SendError,
    parse_messages,
)
from .whatsapp import verify_signature as check_signature

SELF_TEST = ("bom dia", "greeting")
CHALLENGE = re.compile(r"\d{1,64}")


@dataclass
class Runtime:
    settings: Settings
    secrets: Secrets
    kb: KnowledgeBase
    provider: IntentProvider
    attendant: Attendant
    sender: Sender
    metrics: Metrics
    ledger: MessageLedger
    # Key of the message_ref hash, drawn at startup and never logged (RQ-22).
    log_key: bytes = field(default_factory=lambda: token_bytes(32), repr=False)

    def message_ref(self, message_id: str) -> str:
        """A wamid encodes the sender's phone: logs carry this keyed hash instead."""
        return hmac.new(self.log_key, message_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    @property
    def signature_check(self) -> bool:
        """The webhook can accept events: it verifies them, or unsigned ones were allowed."""
        return bool(self.secrets.app_secret) or self.settings.whatsapp.allow_unsigned


@dataclass
class Batch:
    replies: list[tuple[str, str]] = field(default_factory=list)
    retry: bool = False  # a message failed and still has attempts left


def _default_sender(settings: Settings, secrets: Secrets) -> Sender:
    if secrets.access_token and secrets.phone_number_id:
        return CloudApiSender(secrets.access_token, secrets.phone_number_id, settings.whatsapp)
    return RecordingSender()


def self_test(provider: IntentProvider) -> bool:
    text, expected = SELF_TEST
    return provider.classify(text).intent == expected


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, or 413 as soon as it is known to pass `limit` bytes (RQ-33)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise HTTPException(status_code=400, detail="invalid Content-Length")
        if int(declared) > limit:
            raise HTTPException(status_code=413, detail="body too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(
    settings: Settings | None = None,
    secrets: Secrets | None = None,
    kb: KnowledgeBase | None = None,
    sender: Sender | None = None,
    provider: IntentProvider | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    secrets = secrets or Secrets.from_env()
    if secrets.access_token and not secrets.app_secret:
        raise ConfigError(
            "WA_ACCESS_TOKEN is set without WA_APP_SECRET: the service could send messages but "
            "not verify the events it answers; set WA_APP_SECRET (RQ-3)"
        )
    setup_logging(settings.logging)
    kb = kb or load_knowledge_base(settings.knowledge_base)
    provider = provider or build_provider(kb, settings.engine, settings.llm, secrets)
    attendant = Attendant(
        kb, provider, settings.dialogue, switch_threshold=settings.engine.switch_threshold
    )
    wa = settings.whatsapp
    rt = Runtime(
        settings=settings,
        secrets=secrets,
        kb=kb,
        provider=provider,
        attendant=attendant,
        sender=sender or _default_sender(settings, secrets),
        metrics=Metrics(),
        ledger=MessageLedger(
            wa.idempotency_ttl_seconds, wa.idempotency_max_ids, wa.max_processing_attempts
        ),
    )
    demo = settings.demo.enabled
    app = FastAPI(
        title="AI WhatsApp Attendant",
        version=__version__,
        description="WhatsApp Cloud API webhook with an intent engine and human handoff.",
        # The schema documents the demo endpoints; production serves no API docs (RQ-30).
        docs_url="/docs" if demo else None,
        redoc_url="/redoc" if demo else None,
        openapi_url="/openapi.json" if demo else None,
    )
    app.state.rt = rt

    def deliver(phone: str, text: str) -> None:
        try:
            rt.sender.send_text(phone, text)
        except SendError:
            rt.metrics.inc("send_failures")
        except Exception:  # an unexpected sender bug must not kill the worker
            rt.metrics.inc("send_failures")
            log_event(
                "send.failed", logging.ERROR, exc_info=True, phone=mask_phone(phone), status=None
            )

    def account(turn: Turn) -> None:
        if turn.action is Action.NOT_UNDERSTOOD:
            rt.metrics.inc("not_understood")
        if turn.action is Action.UNSUPPORTED:
            rt.metrics.inc("unsupported")
        if turn.handoff_reason is HandoffReason.CUSTOMER_REQUEST:
            rt.metrics.inc("handoff_customer_request")
        elif turn.handoff_reason is HandoffReason.REPEATED_FAILURES:
            rt.metrics.inc("handoff_repeated_failures")
            rt.metrics.inc("not_understood")

    def handle(message: InboundMessage) -> Turn:
        if message.text is None:
            return rt.attendant.handle_unsupported(message.phone, message.kind)
        return rt.attendant.handle(message.phone, message.text)

    def process(messages: list[InboundMessage]) -> Batch:
        """Handle every message of one event; runs in a worker thread (RQ-34)."""
        batch = Batch()
        for message in messages:
            ref, phone = rt.message_ref(message.message_id), mask_phone(message.phone)
            if not rt.ledger.claim(message.message_id):
                rt.metrics.inc("duplicates")
                log_event("message.duplicate", message_ref=ref)
                continue
            rt.metrics.inc("received")
            log_event("message.received", phone=phone, message_ref=ref, kind=message.kind)
            start = time.perf_counter()
            try:
                turn = handle(message)
            except Exception:  # one bad message must not lose the others (RQ-5)
                rt.metrics.inc("processing_errors")
                given_up = rt.ledger.fail(message.message_id)
                if given_up:
                    rt.metrics.inc("dead_letters")
                else:
                    batch.retry = True
                log_event(
                    "message.failed",
                    logging.ERROR,
                    exc_info=True,
                    phone=phone,
                    message_ref=ref,
                    dead_letter=given_up,
                )
                continue
            rt.ledger.complete(message.message_id)
            rt.metrics.observe_latency((time.perf_counter() - start) * 1000)
            account(turn)
            if turn.reply:
                rt.metrics.inc("replied")
                batch.replies.append((message.phone, turn.reply))
            log_event(
                "message.replied",
                phone=phone,
                message_ref=ref,
                intent=turn.intent,
                confidence=turn.confidence,
                action=turn.action.value,
                source=turn.source,
                latency_ms=turn.latency_ms,
            )
        return batch

    @app.get("/webhook", response_class=PlainTextResponse)
    def verify(request: Request) -> PlainTextResponse:
        q = request.query_params
        token = rt.secrets.verify_token
        given = q.get("hub.verify_token", "")
        if not (
            token
            and q.get("hub.mode") == "subscribe"
            and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))
        ):
            raise HTTPException(status_code=403, detail="verification failed")
        challenge = q.get("hub.challenge", "")
        if not CHALLENGE.fullmatch(challenge):
            raise HTTPException(status_code=400, detail="hub.challenge must be 1 to 64 digits")
        return PlainTextResponse(challenge)

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> JSONResponse:
        if not rt.secrets.app_secret and not wa.allow_unsigned:
            log_event("signature.unconfigured", logging.WARNING)
            raise HTTPException(status_code=503, detail="WA_APP_SECRET is not configured")
        try:
            body = await read_body(request, wa.max_body_bytes)
        except HTTPException as exc:
            if exc.status_code == 413:
                rt.metrics.inc("oversized_bodies")
                log_event("body.too_large", logging.WARNING, limit=wa.max_body_bytes)
            raise
        if rt.secrets.app_secret and not check_signature(
            rt.secrets.app_secret, body, request.headers.get("x-hub-signature-256")
        ):
            rt.metrics.inc("invalid_signatures")
            log_event("signature.invalid", logging.WARNING)
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise HTTPException(status_code=400, detail="body is not valid JSON") from exc
        batch = await run_in_threadpool(process, parse_messages(payload))
        for phone, text in batch.replies:
            background.add_task(deliver, phone, text)
        if batch.retry:  # Meta redelivers the event; handled messages are skipped as duplicates
            return JSONResponse({"status": "retry"}, status_code=500, background=background)
        return JSONResponse({"status": "ok"}, background=background)

    @app.get("/health")
    def health() -> JSONResponse:
        checks = {
            "knowledge_base": len(rt.kb.intents) > 0,
            "classifier_self_test": self_test(rt.provider),
            "signature_check": rt.signature_check,
        }
        ok = all(checks.values())
        body = {"status": "ok" if ok else "fail", "version": __version__, "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/metrics")
    def metrics() -> dict[str, float | int]:
        data = rt.metrics.snapshot()
        data["sessions"] = len(rt.attendant.sessions)
        data["learning_queue"] = len(rt.attendant.learning_queue)
        return data

    if demo:  # otherwise /console and /dashboard simply do not exist (404)
        from . import demo as demo_ui

        demo_ui.mount(app, rt)

    return app
