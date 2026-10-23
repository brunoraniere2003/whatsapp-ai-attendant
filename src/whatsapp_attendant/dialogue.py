"""Dialogue manager: one session per phone, slot filling, handoff and the learning queue.

Business rules (SPEC-001, RQ-12 to RQ-18 and RQ-35 to RQ-37):
- an intent that needs the order number asks for it once and answers when it arrives;
- while the number is pending, a confident different intent switches topic; a reply that brings
  a number switches only to an intent that uses the number or hands off;
- the order backend answers only about orders of the phone that asks;
- a cancellation is confirmed with a yes or no question, even with a number given earlier;
- a negated guarded intent ("não quero mais cancelar", "não preciso de atendente") is never
  acted on;
- consecutive failed turns (not understood, invalid or unknown number, unclear answer) up to the
  limit hand off;
- asking for a person hands off at once, and after a handoff the bot stays silent;
- every message that is not understood goes to the learning queue, with the number masked.
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
from .knowledge import (
    BACKEND_FIELDS,
    NOT_UNDERSTOOD,
    UNSUPPORTED,
    WITH_HUMAN,
    Intent,
    KnowledgeBase,
)
from .logs import log_event, mask_phone
from .nlu import Prediction, is_negated, yes_or_no
from .providers import IntentProvider
from .store import Clock, TTLStore


class Action(StrEnum):
    ANSWER = "answer"
    ASK_SLOT = "ask_slot"
    REASK_SLOT = "reask_slot"
    CONFIRM = "confirm"
    DECLINED = "declined"
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
    """State of one phone. `lock` serializes that phone's messages only (RQ-34)."""

    phone: str
    pending_intent: str | None = None  # waiting for its slot
    pending_confirmation: str | None = None  # waiting for a yes or no
    slots: dict[str, str] = field(default_factory=dict)
    failed_turns: int = 0
    handoff_reason: HandoffReason | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def with_human(self) -> bool:
        return self.handoff_reason is not None


@dataclass(frozen=True)
class LearningItem:
    """A message the engine did not understand, waiting to become a new training example."""

    phone: str  # masked
    text: str  # order numbers masked
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

    # public API -------------------------------------------------------------------------------

    def session(self, phone: str) -> Session:
        session, _ = self.sessions.get_or_create(phone, lambda: Session(phone))
        return session

    def handle(self, phone: str, text: str) -> Turn:
        """Answer one text message from `phone`.

        Only messages of the same phone wait for each other; the classification, which may call
        the LLM, never holds a lock shared by other phones.
        """
        start = time.perf_counter()
        session = self.session(phone)
        with session.lock:
            if session.with_human:
                turn = Turn(text, WITH_HUMAN, 1.0, Action.SILENT, None)
            elif session.pending_confirmation:
                turn = self._continue_confirmation(session, text)
            elif session.pending_intent:
                turn = self._continue_slot(session, text)
            else:
                turn = self._new_topic(session, text)
            return replace(
                turn,
                slots=dict(session.slots),
                latency_ms=round((time.perf_counter() - start) * 1000, 3),
            )

    def handle_unsupported(self, phone: str, kind: str) -> Turn:
        """A media message (image, audio...): ask for text, unless a human already has it."""
        session = self.session(phone)
        with session.lock:
            if session.with_human:
                return Turn(f"[{kind}]", WITH_HUMAN, 1.0, Action.SILENT, None)
            reply = self.kb.render(self.kb.unsupported_reply)
            return Turn(f"[{kind}]", UNSUPPORTED, 1.0, Action.UNSUPPORTED, reply)

    # helpers ----------------------------------------------------------------------------------

    def _classify(self, text: str) -> Prediction:
        """Classify with the order number and its cue words masked: they say nothing about the
        intent, and they never reach an LLM."""
        return self.provider.classify(self.kb.mask_slots(text))

    def _negated(self, p: Prediction, text: str) -> bool:
        """The customer negated the key word of the predicted intent (RQ-35)."""
        if not p.understood:
            return False
        return is_negated(self.kb.mask_slots(text), self.kb.intent(p.intent).negation_terms)

    def _fields(self, intent: Intent, session: Session) -> dict[str, str]:
        return {intent.slot: session.slots[intent.slot]} if intent.slot else {}

    def _turn(self, text: str, intent: str, p: Prediction, action: Action, reply: str) -> Turn:
        return Turn(
            text, intent, p.confidence, action, reply, source=p.source, best_guess=p.best_guess
        )

    def _failed(self, session: Session) -> bool:
        """Count a failed turn; True when the limit was reached and the session must hand off."""
        session.failed_turns += 1
        return session.failed_turns >= self.settings.max_failed_turns

    # rules ------------------------------------------------------------------------------------

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
        session.pending_intent = session.pending_confirmation = None
        log_event("handoff", phone=mask_phone(session.phone), reason=reason.value)
        return replace(
            self._turn(text, intent, prediction, Action.HANDOFF, self.kb.render(reply)),
            handoff_reason=reason,
        )

    def _failure(self, session: Session, text: str, p: Prediction, intent: str, reply: str) -> Turn:
        """A failed turn: hand off at the limit, otherwise `reply` (a re-ask)."""
        if self._failed(session):
            return self._handoff(
                session, text, p, HandoffReason.REPEATED_FAILURES, self.kb.handoff_reply, intent
            )
        action = Action.CONFIRM if session.pending_confirmation else Action.REASK_SLOT
        return self._turn(text, intent, p, action, reply)

    def _declined(self, session: Session, text: str, p: Prediction, intent: str) -> Turn:
        """The customer said no to `intent`: drop it if pending, act on nothing (RQ-35)."""
        if session.pending_intent == intent:
            session.pending_intent = None
        if session.pending_confirmation == intent:
            session.pending_confirmation = None
        session.failed_turns = 0
        log_event("declined", phone=mask_phone(session.phone), intent=intent)
        return self._turn(text, intent, p, Action.DECLINED, self.kb.render(self.kb.declined_reply))

    def _resolve(
        self, session: Session, intent: Intent, text: str, p: Prediction, confirmed: bool = False
    ) -> Turn:
        """Answer `intent`, whose slot is filled: look the order up, confirm first if needed."""
        fields = self._fields(intent, session)
        if intent.slot in BACKEND_FIELDS:
            value = session.slots[intent.slot]
            found = self.backend.lookup(value, session.phone)
            if found is None:  # unknown order, or another phone's (RQ-37)
                del session.slots[intent.slot]
                session.pending_intent = intent.name
                slot = self.kb.slots[intent.slot]
                reply = self.kb.render(slot.not_found or slot.invalid, **fields)
                return self._failure(session, text, p, intent.name, reply)
            fields.update(found)
        if intent.confirm and not confirmed:
            session.pending_confirmation = intent.name
            log_event("confirmation.asked", phone=mask_phone(session.phone), intent=intent.name)
            question = self.kb.render(intent.confirm, **self._fields(intent, session))
            return self._turn(text, intent.name, p, Action.CONFIRM, question)
        return self._turn(
            text, intent.name, p, Action.ANSWER, self.kb.render(intent.reply, **fields)
        )

    def _not_understood(self, session: Session, text: str, p: Prediction) -> Turn:
        masked = " ".join(self.kb.mask_slots(text).split())
        self.learning_queue.append(
            LearningItem(mask_phone(session.phone), masked, p.best_guess, p.confidence)
        )
        log_event(
            "learning.queued", logging.DEBUG, best_guess=p.best_guess, confidence=p.confidence
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
        return self._turn(
            text,
            NOT_UNDERSTOOD,
            p,
            Action.NOT_UNDERSTOOD,
            self.kb.render(self.kb.not_understood_reply),
        )

    def _new_topic(self, session: Session, text: str, prediction: Prediction | None = None) -> Turn:
        p = prediction or self._classify(text)
        if self._negated(p, text):
            return self._declined(session, text, p, p.intent)
        if not p.understood:
            return self._not_understood(session, text, p)
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
                return self._turn(text, intent.name, p, Action.ASK_SLOT, self.kb.render(slot.ask))
        return self._resolve(session, intent, text, p)

    def _switches(self, p: Prediction, pending: Intent, with_number: bool) -> bool:
        """A confident different intent leaves the pending question (RQ-13). A reply that
        carries a number only switches to an intent that uses it or hands off."""
        if not p.understood or p.intent == pending.name or p.confidence < self.switch_threshold:
            return False
        if not with_number:
            return True
        other = self.kb.intent(p.intent)
        return other.handoff or other.slot == pending.slot

    def _continue_slot(self, session: Session, text: str) -> Turn:
        intent = self.kb.intent(session.pending_intent or "")
        slot = self.kb.slots[intent.slot or ""]
        value = slot.find(text)
        p = self._classify(text)
        negated = self._negated(p, text)
        if negated and p.intent == intent.name:  # "não quero mais cancelar"
            return self._declined(session, text, p, intent.name)
        if not negated and self._switches(p, intent, with_number=value is not None):
            session.pending_intent = None
            if value:  # the number belongs to the new topic (or to the person taking over)
                session.slots[slot.name] = value
            return self._new_topic(session, text, p)
        if value:
            session.slots[slot.name] = value
            session.pending_intent = None
            session.failed_turns = 0
            return self._resolve(session, intent, text, Prediction(intent.name, 1.0, source="slot"))
        return self._failure(session, text, p, intent.name, self.kb.render(slot.invalid))

    def _continue_confirmation(self, session: Session, text: str) -> Turn:
        intent = self.kb.intent(session.pending_confirmation or "")
        answer = yes_or_no(self.kb.mask_slots(text), intent.negation_terms)
        sure = Prediction(intent.name, 1.0, source="confirmation")
        if answer is True:
            session.pending_confirmation = None
            session.failed_turns = 0
            return self._resolve(session, intent, text, sure, confirmed=True)
        if answer is False:
            return self._declined(session, text, sure, intent.name)
        p = self._classify(text)
        if not self._negated(p, text) and self._switches(p, intent, with_number=False):
            session.pending_confirmation = None
            return self._new_topic(session, text, p)
        question = self.kb.render(intent.confirm or "", **self._fields(intent, session))
        return self._failure(session, text, p, intent.name, question)
