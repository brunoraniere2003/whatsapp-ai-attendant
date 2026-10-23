"""FastAPI app: Cloud API webhook, health, metrics and the optional demo UI.

Run with `python -m whatsapp_attendant serve` (or `uvicorn --factory
whatsapp_attendant.api:create_app`). Building the app loads and validates the configuration and the
knowledge base, so a bad file stops the service at startup (RQ-19, RQ-20).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .config import Secrets, Settings, load_settings
from .dialogue import Action, Attendant, HandoffReason, Turn
from .knowledge import KnowledgeBase, load_knowledge_base
from .logs import log_event, mask_phone, setup_logging
from .metrics import Metrics
from .providers import IntentProvider, build_provider
from .store import TTLStore
from .whatsapp import CloudApiSender, RecordingSender, Sender, SendError, parse_messages
from .whatsapp import verify_signature as check_signature

SELF_TEST = ("bom dia", "greeting")


@dataclass
class Runtime:
    settings: Settings
    secrets: Secrets
    kb: KnowledgeBase
    provider: IntentProvider
    attendant: Attendant
    sender: Sender
    metrics: Metrics
    seen: TTLStore[None]


def _default_sender(settings: Settings, secrets: Secrets) -> Sender:
    if secrets.access_token and secrets.phone_number_id:
        return CloudApiSender(secrets.access_token, secrets.phone_number_id, settings.whatsapp)
    return RecordingSender()


def self_test(provider: IntentProvider) -> bool:
    text, expected = SELF_TEST
    return provider.classify(text).intent == expected


def create_app(
    settings: Settings | None = None,
    secrets: Secrets | None = None,
    kb: KnowledgeBase | None = None,
    sender: Sender | None = None,
    provider: IntentProvider | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    secrets = secrets or Secrets.from_env()
    setup_logging(settings.logging)
    kb = kb or load_knowledge_base(settings.knowledge_base)
    provider = provider or build_provider(kb, settings.engine, settings.llm, secrets)
    attendant = Attendant(
        kb, provider, settings.dialogue, switch_threshold=settings.engine.switch_threshold
    )
    rt = Runtime(
        settings=settings,
        secrets=secrets,
        kb=kb,
        provider=provider,
        attendant=attendant,
        sender=sender or _default_sender(settings, secrets),
        metrics=Metrics(),
        seen=TTLStore(
            settings.whatsapp.idempotency_ttl_seconds, settings.whatsapp.idempotency_max_ids
        ),
    )
    app = FastAPI(
        title="AI WhatsApp Attendant",
        version=__version__,
        description="WhatsApp Cloud API webhook with an intent engine and human handoff.",
    )
    app.state.rt = rt

    def deliver(phone: str, text: str) -> None:
        try:
            rt.sender.send_text(phone, text)
        except SendError:
            rt.metrics.inc("send_failures")
        except Exception:  # an unexpected sender bug must not kill the worker
            rt.metrics.inc("send_failures")
            log_event("send.failed", logging.ERROR, phone=mask_phone(phone), status=None)

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

    @app.get("/webhook", response_class=PlainTextResponse)
    def verify(request: Request) -> PlainTextResponse:
        q = request.query_params
        token = rt.secrets.verify_token
        if token and q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == token:
            return PlainTextResponse(q.get("hub.challenge", ""))
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
        body = await request.body()
        if rt.secrets.app_secret and not check_signature(
            rt.secrets.app_secret, body, request.headers.get("x-hub-signature-256")
        ):
            rt.metrics.inc("invalid_signatures")
            log_event("signature.invalid", logging.WARNING)
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="body is not valid JSON") from exc
        for message in parse_messages(payload):
            if not rt.seen.add_if_absent(message.message_id):
                rt.metrics.inc("duplicates")
                log_event("message.duplicate", message_id=message.message_id)
                continue
            rt.metrics.inc("received")
            phone = mask_phone(message.phone)
            log_event(
                "message.received", phone=phone, message_id=message.message_id, kind=message.kind
            )
            start = time.perf_counter()
            if message.text is None:
                turn = rt.attendant.handle_unsupported(message.phone, message.kind)
            else:
                turn = rt.attendant.handle(message.phone, message.text)
            rt.metrics.observe_latency((time.perf_counter() - start) * 1000)
            account(turn)
            if turn.reply:
                rt.metrics.inc("replied")
                background.add_task(deliver, message.phone, turn.reply)
            log_event(
                "message.replied",
                phone=phone,
                intent=turn.intent,
                confidence=turn.confidence,
                action=turn.action.value,
                source=turn.source,
                latency_ms=turn.latency_ms,
            )
        return {"status": "ok"}

    @app.get("/health")
    def health() -> JSONResponse:
        checks = {
            "knowledge_base": len(rt.kb.intents) > 0,
            "classifier_self_test": self_test(rt.provider),
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

    if settings.demo.enabled:  # otherwise /console and /dashboard simply do not exist (404)
        from . import demo

        demo.mount(app, rt)

    return app
