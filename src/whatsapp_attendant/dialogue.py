"""Dialogue manager: one session per phone, slot filling, handoff and the learning queue.

Business rules (SPEC-001, RQ-12 to RQ-18):
- an intent that needs the order number asks for it once and answers when it arrives;
- while the number is pending, a confident different intent switches topic;
- consecutive failed turns (not understood or invalid number) up to the limit hand off;
- asking for a person hands off at once, and after a handoff the bot stays silent;
- every message that is not understood goes to the learning queue.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .backends import FakeOrderBackend, OrderBackend
from .config import DialogueSettings
from .knowledge import NOT_UNDERSTOOD, UNSUPPORTED, WITH_HUMAN, Intent, KnowledgeBase
from .logs import log_event, mask_phone
from .nlu import Prediction
from .providers import IntentProvider
from .store import Clock, TTLStore


class Action(StrEnum):
    ANSWER = "answer"
    ASK_SLOT = "ask_slot"
    REASK_SLOT = "reask_slot"
    NOT_UNDERSTOOD = "not_understood"
    HANDOFF = "handoff"
    SILENT = "silent"
    UNSUPPORTED = "unsupported"


class HandoffReason(StrEnum):
    CUSTOMER_REQUEST = "customer_request"
    REPEATED_FAILURES = "repeated_failures"


@dataclass(frozen=True)
class Turn:
    text: str
    intent: str
    confidence: float
    action: Action
    reply: str | None
    source: str = "local"
    best_guess: str | None = None
    handoff_reason: HandoffReason | None = None
    slots: Mapping[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass
class Session:
    phone: str
    turns: list[Turn] = field(default_factory=list)
    pending_intent: str | None = None
    slots: dict[str, str] = field(default_factory=dict)
    failed_turns: int = 0
    handoff_reason: HandoffReason | None = None

    @property
    def with_human(self) -> bool:
        return self.handoff_reason is not None


@dataclass(frozen=True)
class LearningItem:
    """A message the engine did not understand, waiting to become a new training example."""

    phone: str  # masked
    text: str
    best_guess: str | None
    confidence: float


class Attendant:
    def __init__(
        self,
        kb: KnowledgeBase,
        provider: IntentProvider,
        settings: DialogueSettings | None = None,
        switch_threshold: float = 0.45,
        backend: OrderBackend | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.kb = kb
        self.provider = provider
        self.settings = settings or DialogueSettings()
        self.switch_threshold = switch_threshold
        self.backend = backend or FakeOrderBackend()
        self.sessions: TTLStore[Session] = TTLStore(
            self.settings.session_ttl_seconds, self.settings.max_sessions, clock
        )
        self.learning_queue: deque[LearningItem] = deque(maxlen=self.settings.learning_queue_size)
        self._lock = threading.RLock()

    # public API -------------------------------------------------------------------------------

    def session(self, phone: str) -> Session:
        session, _ = self.sessions.get_or_create(phone, lambda: Session(phone))
        return session

    def handle(self, phone: str, text: str) -> Turn:
        """Answer one text message from `phone`."""
        start = time.perf_counter()
        with self._lock:
            session = self.session(phone)
            if session.with_human:
                turn = Turn(text, WITH_HUMAN, 1.0, Action.SILENT, None)
            elif session.pending_intent:
                turn = self._continue_slot(session, text)
            else:
                turn = self._new_topic(session, text)
            turn = replace(
                turn,
                slots=dict(session.slots),
                latency_ms=round((time.perf_counter() - start) * 1000, 3),
            )
            session.turns.append(turn)
        return turn

    def handle_unsupported(self, phone: str, kind: str) -> Turn:
        """A media message (image, audio...): ask for text, unless a human already has it."""
        with self._lock:
            session = self.session(phone)
            if session.with_human:
                turn = Turn(f"[{kind}]", WITH_HUMAN, 1.0, Action.SILENT, None)
            else:
                reply = self.kb.render(self.kb.unsupported_reply)
                turn = Turn(f"[{kind}]", UNSUPPORTED, 1.0, Action.UNSUPPORTED, reply)
            session.turns.append(turn)
        return turn

    # rules ------------------------------------------------------------------------------------

    def _answer(self, session: Session, intent: Intent, text: str, prediction: Prediction) -> Turn:
        fields: dict[str, str] = {}
        if intent.slot:
            value = session.slots[intent.slot]
            fields[intent.slot] = value
            if intent.slot == "order_number":
                fields.update(self.backend.lookup(value))
        return Turn(
            text,
            intent.name,
            prediction.confidence,
            Action.ANSWER,
            self.kb.render(intent.reply, **fields),
            source=prediction.source,
            best_guess=prediction.best_guess,
        )

    def _handoff(
        self,
        session: Session,
        text: str,
        prediction: Prediction,
        reason: HandoffReason,
        reply: str,
        intent: str,
    ) -> Turn:
        session.handoff_reason = reason
        session.pending_intent = None
        log_event("handoff", phone=mask_phone(session.phone), reason=reason.value)
        return Turn(
            text,
            intent,
            prediction.confidence,
            Action.HANDOFF,
            self.kb.render(reply),
            source=prediction.source,
            best_guess=prediction.best_guess,
            handoff_reason=reason,
        )

    def _failed(self, session: Session) -> bool:
        """Count a failed turn; True when the limit was reached and the session must hand off."""
        session.failed_turns += 1
        return session.failed_turns >= self.settings.max_failed_turns

    def _new_topic(self, session: Session, text: str, prediction: Prediction | None = None) -> Turn:
        p = prediction or self.provider.classify(self.kb.mask_slots(text))
        if not p.understood:
            self.learning_queue.append(
                LearningItem(mask_phone(session.phone), text, p.best_guess, p.confidence)
            )
            log_event(
                "learning.queued",
                logging.DEBUG,
                best_guess=p.best_guess,
                confidence=p.confidence,
            )
            if self._failed(session):
                return self._handoff(
                    session,
                    text,
                    p,
                    HandoffReason.REPEATED_FAILURES,
                    self.kb.handoff_reply,
                    NOT_UNDERSTOOD,
                )
            return Turn(
                text,
                NOT_UNDERSTOOD,
                p.confidence,
                Action.NOT_UNDERSTOOD,
                self.kb.render(self.kb.not_understood_reply),
                source=p.source,
                best_guess=p.best_guess,
            )
        session.failed_turns = 0
        intent = self.kb.intent(p.intent)
        if intent.handoff:
            return self._handoff(
                session, text, p, HandoffReason.CUSTOMER_REQUEST, intent.reply, intent.name
            )
        if intent.slot:
            slot = self.kb.slots[intent.slot]
            value = slot.find(text)
            if value:
                session.slots[intent.slot] = value
            elif intent.slot not in session.slots:
                session.pending_intent = intent.name
                return Turn(
                    text,
                    intent.name,
                    p.confidence,
                    Action.ASK_SLOT,
                    self.kb.render(slot.ask),
                    source=p.source,
                    best_guess=p.best_guess,
                )
        return self._answer(session, intent, text, p)

    def _continue_slot(self, session: Session, text: str) -> Turn:
        intent = self.kb.intent(session.pending_intent or "")
        slot = self.kb.slots[intent.slot or ""]
        value = slot.find(text)
        if value:
            session.slots[slot.name] = value
            session.pending_intent = None
            session.failed_turns = 0
            return self._answer(session, intent, text, Prediction(intent.name, 1.0, source="slot"))
        p = self.provider.classify(self.kb.mask_slots(text))
        if p.understood and p.intent != intent.name and p.confidence >= self.switch_threshold:
            session.pending_intent = None
            return self._new_topic(session, text, p)
        if self._failed(session):
            return self._handoff(
                session,
                text,
                p,
                HandoffReason.REPEATED_FAILURES,
                self.kb.handoff_reply,
                intent.name,
            )
        return Turn(
            text,
            intent.name,
            p.confidence,
            Action.REASK_SLOT,
            self.kb.render(slot.invalid),
            source=p.source,
            best_guess=p.best_guess,
        )
