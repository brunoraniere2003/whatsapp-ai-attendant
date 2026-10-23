"""Knowledge base: intents, training examples, replies and slots, loaded from TOML (RQ-20)."""

from __future__ import annotations

import re
import string
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

NOT_UNDERSTOOD = "not_understood"
WITH_HUMAN = "with_human"
UNSUPPORTED = "unsupported"
RESERVED = frozenset({NOT_UNDERSTOOD, WITH_HUMAN, UNSUPPORTED, "none"})
ALWAYS_AVAILABLE = frozenset({"store", "hours"})
# Fields the order backend adds when an intent collects the order number.
BACKEND_FIELDS = {"order_number": frozenset({"order_status", "payment_status"})}
MIN_EXAMPLES = 3


class KnowledgeBaseError(ValueError):
    """The knowledge base file is malformed or inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Store(_Strict):
    name: str = Field(min_length=1)
    hours: str = Field(min_length=1)


class _Replies(_Strict):
    not_understood: str = Field(min_length=1)
    handoff: str = Field(min_length=1)
    unsupported: str = Field(min_length=1)


class _Slot(_Strict):
    pattern: str = Field(min_length=1)
    cue: str = ""  # words that introduce the value ("pedido", "nº"), masked with it
    ask: str = Field(min_length=1)
    invalid: str = Field(min_length=1)

    @field_validator("pattern", "cue")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return value


class _Intent(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    examples: list[str]
    reply: str = Field(min_length=1)
    slot: str | None = None
    handoff: bool = False


class _File(_Strict):
    store: _Store
    replies: _Replies
    slots: dict[str, _Slot] = {}
    intents: list[_Intent] = Field(min_length=1)


@dataclass(frozen=True)
class Slot:
    name: str
    pattern: re.Pattern[str]
    ask: str
    invalid: str
    mask: re.Pattern[str] | None = None

    def find(self, text: str) -> str | None:
        match = self.pattern.search(text)
        return match.group(0) if match else None


@dataclass(frozen=True)
class Intent:
    name: str
    description: str
    examples: tuple[str, ...]
    reply: str
    slot: str | None = None
    handoff: bool = False


@dataclass(frozen=True)
class KnowledgeBase:
    store_name: str
    hours: str
    not_understood_reply: str
    handoff_reply: str
    unsupported_reply: str
    intents: tuple[Intent, ...]
    slots: dict[str, Slot]

    def intent(self, name: str) -> Intent:
        for item in self.intents:
            if item.name == name:
                return item
        raise KeyError(name)

    @property
    def intent_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.intents)

    def labeled_examples(self) -> list[tuple[str, str]]:
        return [(example, item.name) for item in self.intents for example in item.examples]

    def render(self, template: str, **fields: str) -> str:
        return template.format(store=self.store_name, hours=self.hours, **fields)

    def mask_slots(self, text: str) -> str:
        """Remove slot values and their cue words before classification.

        "o boleto venceu, pedido 123456" is classified as "o boleto venceu,": the number and the
        word that introduces it say nothing about the intent, and they never reach an LLM.
        """
        for slot in self.slots.values():
            text = (slot.mask or slot.pattern).sub(" ", text)
        return text


def _placeholders(template: str) -> set[str]:
    try:
        return {field for _, field, _, _ in string.Formatter().parse(template) if field}
    except ValueError as exc:
        raise KnowledgeBaseError(f"malformed template {template!r}: {exc}") from exc


def _check(data: _File) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for intent in data.intents:
        where = f"intent {intent.name!r}"
        if intent.name in RESERVED:
            problems.append(f"{where}: the name is reserved")
        if intent.name in seen:
            problems.append(f"{where}: repeated intent name")
        seen.add(intent.name)
        examples = [e for e in intent.examples if e.strip()]
        if len(examples) < MIN_EXAMPLES:
            problems.append(f"{where}: needs at least {MIN_EXAMPLES} examples")
        if intent.slot and intent.slot not in data.slots:
            problems.append(f"{where}: slot {intent.slot!r} is not defined in [slots]")
        if intent.slot and intent.handoff:
            problems.append(f"{where}: an intent cannot both collect a slot and hand off")
        allowed = set(ALWAYS_AVAILABLE)
        if intent.slot:
            allowed |= {intent.slot} | BACKEND_FIELDS.get(intent.slot, frozenset())
        unknown = _placeholders(intent.reply) - allowed
        if unknown:
            problems.append(f"{where}: unknown placeholders {sorted(unknown)}")
    for name, template in data.replies.model_dump().items():
        unknown = _placeholders(template) - ALWAYS_AVAILABLE
        if unknown:
            problems.append(f"reply {name!r}: unknown placeholders {sorted(unknown)}")
    return problems


def parse_knowledge_base(data: dict) -> KnowledgeBase:
    try:
        parsed = _File.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise KnowledgeBaseError(f"invalid knowledge base: {details}") from exc
    problems = _check(parsed)
    if problems:
        raise KnowledgeBaseError("invalid knowledge base: " + "; ".join(problems))
    slots = {
        name: Slot(
            name,
            re.compile(s.pattern),
            s.ask,
            s.invalid,
            re.compile(rf"(?:\b(?:{s.cue})\s*)?(?:{s.pattern})", re.IGNORECASE) if s.cue else None,
        )
        for name, s in parsed.slots.items()
    }
    intents = tuple(
        Intent(
            name=i.name,
            description=i.description,
            examples=tuple(e for e in i.examples if e.strip()),
            reply=i.reply,
            slot=i.slot,
            handoff=i.handoff,
        )
        for i in parsed.intents
    )
    return KnowledgeBase(
        store_name=parsed.store.name,
        hours=parsed.store.hours,
        not_understood_reply=parsed.replies.not_understood,
        handoff_reply=parsed.replies.handoff,
        unsupported_reply=parsed.replies.unsupported,
        intents=intents,
        slots=slots,
    )


def bundled_text(name: str) -> str:
    """Text of a file bundled under `whatsapp_attendant/data/`."""
    return resources.files("whatsapp_attendant").joinpath("data", name).read_text(encoding="utf-8")


def load_knowledge_base(path: str | Path | None = None) -> KnowledgeBase:
    """Load the knowledge base from `path`, or the bundled one when `path` is empty."""
    try:
        text = (
            Path(path).read_text(encoding="utf-8") if path else bundled_text("knowledge_base.toml")
        )
        data = tomllib.loads(text)
    except FileNotFoundError as exc:
        raise KnowledgeBaseError(f"knowledge base not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise KnowledgeBaseError(f"knowledge base is not valid TOML: {exc}") from exc
    return parse_knowledge_base(data)
