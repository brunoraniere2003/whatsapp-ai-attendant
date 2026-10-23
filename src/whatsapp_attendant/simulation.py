"""Seeded simulation of customer conversations, scored against the customer's real question.

Customer messages come from the frozen test split (held out from training and dev, ADR-005), with
typos and filler added at random. Each message carries what the customer meant by it, so every
bot turn can be judged (RQ-29):

- `resolved`: the bot answered the main question with no handoff and never gave a wrong answer
  (a reply to something the customer did not mean, a confirmed wrong cancellation included). Only
  a greeting taken for a goodbye, or the reverse, is forgiven: both are small talk.
- `misrouted`: not resolved, and the bot gave a wrong answer or started a wrong flow (asked for an
  order number or a confirmation for a question the customer did not ask).
- `abandoned`: not resolved, but the bot never gave a wrong answer: it rejected the question, the
  customer rephrased once and still got no answer, and left.
- handoffs: on request, after failed turns, or without a request.

The simulated customer rephrases once when the main question is rejected or when the bot asks for
an order number they do not have, says yes to a confirmation of their real question and no to any
other.
"""

from __future__ import annotations

import random
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .config import Settings
from .dialogue import Action, Attendant, HandoffReason, Turn
from .evaluation import OUT_OF_SCOPE, Split
from .knowledge import KnowledgeBase
from .logs import mask_phone
from .providers import LocalProvider

# Share of each main question in the simulated traffic (weights, not percentages).
INTENT_WEIGHTS = {
    "order_status": 28,
    "invoice_copy": 20,
    "payment_status": 16,
    "return_exchange": 12,
    "business_hours": 9,
    "cancel_order": 8,
    "human_agent": 7,
}
SUFFIXES = ("", "", "", " por favor", " urgente", "!!", "?", " ...", " pfv")
DONT_KNOW = ("não sei o número", "não lembro", "nao tenho aqui agora", "onde eu vejo isso?")
NUMBER_REPLIES = ("{n}", "pedido {n}", "é o {n}", "o número é {n}", "nº {n}", "{n} esse aqui")
YES_REPLIES = ("sim", "isso, pode cancelar", "s", "sim, confirmo", "pode cancelar sim")
NO_REPLIES = ("não", "nao, não quero cancelar", "não, era outra coisa")
SMALL_TALK = frozenset({"greeting", "goodbye"})
FLOWS = (Action.ASK_SLOT, Action.REASK_SLOT, Action.CONFIRM)
MAX_TURNS = 8
OUTCOMES = (
    "resolved",
    "requested_handoff",
    "failure_handoff",
    "unrequested_handoff",
    "misrouted",
    "abandoned",
)


@dataclass(frozen=True)
class SimulationConfig:
    conversations: int = 300
    seed: int = 42
    greeting_rate: float = 0.6
    out_of_scope_rate: float = 0.08
    typo_rate: float = 0.3
    number_in_first_message_rate: float = 0.35
    dont_know_rate: float = 0.2
    goodbye_rate: float = 0.5
    # Rephrase once after a rejection or a wrong confirmation. Off, the run measures how much of
    # the result depends on that patience (reported as a sensitivity in metricas.json).
    rephrase_after_miss: bool = True


@dataclass
class Conversation:
    phone: str
    main_intent: str
    turns: list[Turn] = field(default_factory=list)
    meant: list[str] = field(default_factory=list)  # what the customer meant, one per turn
    outcome: str = ""


def add_typo(text: str, rng: random.Random) -> str:
    """One realistic slip: drop, swap or double a letter, or type without accents."""
    words = text.split(" ")
    candidates = [i for i, w in enumerate(words) if len(w) >= 4 and w.isalpha()]
    kind = rng.choice(("drop", "swap", "double", "accents"))
    if kind == "accents" or not candidates:
        decomposed = unicodedata.normalize("NFKD", text)
        return "".join(c for c in decomposed if not unicodedata.combining(c))
    index = rng.choice(candidates)
    word = words[index]
    pos = rng.randrange(1, len(word) - 1)
    if kind == "drop":
        word = word[:pos] + word[pos + 1 :]
    elif kind == "swap":
        word = word[:pos] + word[pos + 1] + word[pos] + word[pos + 2 :]
    else:
        word = word[:pos] + word[pos] + word[pos:]
    words[index] = word
    return " ".join(words)


def _phone(rng: random.Random) -> str:
    return "55119" + "".join(rng.choice("0123456789") for _ in range(8))


def is_wrong(turn: Turn, wanted: str) -> bool:
    """The bot replied about something the customer did not mean (greeting and goodbye mixed up
    with each other are forgiven: both are small talk)."""
    small_talk_mixup = turn.intent in SMALL_TALK and wanted in SMALL_TALK
    return turn.intent != wanted and not small_talk_mixup


def _answered_wrong(conv: Conversation) -> bool:
    return any(
        t.action is Action.ANSWER and is_wrong(t, m)
        for t, m in zip(conv.turns, conv.meant, strict=True)
    )


def classify_outcome(main_intent: str, turns: list[Turn], meant: list[str] | None = None) -> str:
    """Outcome of one conversation; `meant` is what the customer meant by each message (by
    default, the main question for every message)."""
    meant = meant if meant is not None else [main_intent] * len(turns)
    handoff = next((t for t in turns if t.action is Action.HANDOFF), None)
    if handoff is not None:
        if handoff.handoff_reason is HandoffReason.REPEATED_FAILURES:
            return "failure_handoff"
        return "requested_handoff" if main_intent == "human_agent" else "unrequested_handoff"
    judged = list(zip(turns, meant, strict=True))
    wrong_answer = any(t.action is Action.ANSWER and is_wrong(t, m) for t, m in judged)
    wrong_flow = any(t.action in FLOWS and is_wrong(t, m) for t, m in judged)
    answered = any(t.action is Action.ANSWER and t.intent == main_intent for t in turns)
    if answered and not wrong_answer:
        return "resolved"
    if wrong_answer or wrong_flow:
        return "misrouted"
    return "abandoned"


def _script(
    rng: random.Random, kb: KnowledgeBase, test: Split, cfg: SimulationConfig
) -> tuple[str, str, list[tuple[str, str]]]:
    """The main intent, its base phrase and the opening messages (text, meant) of one customer."""
    messages: list[tuple[str, str]] = []
    if rng.random() < cfg.greeting_rate:
        messages.append((rng.choice(test.phrases["greeting"]), "greeting"))
    if rng.random() < cfg.out_of_scope_rate:
        messages.append((rng.choice(test.phrases[OUT_OF_SCOPE]), OUT_OF_SCOPE))
    main = rng.choices(list(INTENT_WEIGHTS), weights=list(INTENT_WEIGHTS.values()))[0]
    base = rng.choice(test.phrases[main])
    question = base
    if rng.random() < cfg.typo_rate:
        question = add_typo(question, rng)
    question += rng.choice(SUFFIXES)
    if kb.intent(main).slot == "order_number" and rng.random() < cfg.number_in_first_message_rate:
        question += f", pedido {rng.randint(100000, 999999)}"
    messages.append((question, main))
    return main, base, messages


class _Customer:
    """One simulated customer: the message queue and the one rephrase they allow themselves."""

    def __init__(self, rng: random.Random, main: str, base: str, test: Split) -> None:
        self.rng = rng
        self.main = main
        self.others = [t for t in test.phrases[main] if t != base]
        self.queue: list[tuple[str, str]] = []
        self.rephrased = False

    def say(self, text: str, at: int = 0) -> None:
        self.queue.insert(at, (text, self.main))

    def rephrase(self, at: int = 0) -> None:
        """Ask the main question again in other words, once per conversation."""
        if not self.rephrased and self.others:
            self.say(self.rng.choice(self.others), at)
            self.rephrased = True


def _converse(
    attendant: Attendant,
    rng: random.Random,
    kb: KnowledgeBase,
    test: Split,
    cfg: SimulationConfig,
) -> Conversation:
    phone = _phone(rng)
    main, base, messages = _script(rng, kb, test, cfg)
    has_order = kb.intent(main).slot == "order_number"
    customer = _Customer(rng, main, base, test)
    customer.queue.extend(messages)
    conv = Conversation(phone, main)
    said_dont_know = False
    while customer.queue and len(conv.turns) < MAX_TURNS:
        text, meant = customer.queue.pop(0)
        turn = attendant.handle(phone, text)
        conv.turns.append(turn)
        conv.meant.append(meant)
        if turn.action is Action.HANDOFF:
            break
        if turn.action is Action.CONFIRM:
            if turn.intent == main:
                customer.say(rng.choice(YES_REPLIES))
            else:  # "cancel?" for another question: no, and then ask again
                customer.say(rng.choice(NO_REPLIES))
                if cfg.rephrase_after_miss:
                    customer.rephrase(at=1)
        elif turn.action is Action.NOT_UNDERSTOOD and meant == main:
            if cfg.rephrase_after_miss:
                customer.rephrase()
        elif turn.action in (Action.ASK_SLOT, Action.REASK_SLOT):
            if not has_order:
                # Asked for an order number the customer does not have: they rephrase once.
                customer.rephrase()
            elif not said_dont_know and rng.random() < cfg.dont_know_rate:
                customer.say(rng.choice(DONT_KNOW))
                said_dont_know = True
            else:
                number = rng.randint(100000, 999999)
                customer.say(rng.choice(NUMBER_REPLIES).format(n=number))
    if not any(t.action is Action.HANDOFF for t in conv.turns) and rng.random() < cfg.goodbye_rate:
        conv.turns.append(attendant.handle(phone, rng.choice(test.phrases["goodbye"])))
        conv.meant.append("goodbye")
    conv.outcome = classify_outcome(main, conv.turns, conv.meant)
    return conv


def simulate(
    kb: KnowledgeBase, settings: Settings, test: Split, cfg: SimulationConfig | None = None
) -> dict:
    cfg = cfg or SimulationConfig()
    attendant = Attendant(
        kb,
        LocalProvider(kb, settings.engine),
        settings.dialogue,
        switch_threshold=settings.engine.switch_threshold,
    )
    conversations = [
        # One generator per conversation: runs that differ only in customer behavior (the
        # sensitivity run) still meet the same customers with the same first messages.
        _converse(attendant, random.Random(f"{cfg.seed}:{index}"), kb, test, cfg)
        for index in range(cfg.conversations)
    ]
    return _summarize(conversations, attendant, cfg)


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _summarize(
    conversations: list[Conversation], attendant: Attendant, cfg: SimulationConfig
) -> dict:
    total = len(conversations)
    outcomes = Counter(c.outcome for c in conversations)
    turns = [t for c in conversations for t in c.turns]
    human_requests = sum(1 for c in conversations if c.main_intent == "human_agent")
    handoffs = (
        outcomes["requested_handoff"]
        + outcomes["failure_handoff"]
        + outcomes["unrequested_handoff"]
    )
    actions = Counter(t.action.value for t in turns)
    return {
        "conversations": total,
        "customer_messages": len(turns),
        "messages_per_conversation": round(len(turns) / total, 2) if total else 0.0,
        "main_intents": dict(Counter(c.main_intent for c in conversations).most_common()),
        "outcomes": {name: outcomes[name] for name in OUTCOMES},
        "resolution_rate": _rate(outcomes["resolved"], total),
        "resolution_rate_excluding_human_requests": _rate(
            outcomes["resolved"], total - human_requests
        ),
        "correctly_handled_rate": _rate(
            outcomes["resolved"] + outcomes["requested_handoff"], total
        ),
        "handoff_rate": _rate(handoffs, total),
        "misrouted_rate": _rate(outcomes["misrouted"], total),
        # misrouted conversations that got a wrong answer, not only a wrong question
        "misrouted_with_wrong_answer": sum(
            1 for c in conversations if c.outcome == "misrouted" and _answered_wrong(c)
        ),
        "abandoned_rate": _rate(outcomes["abandoned"], total),
        "actions": {name.value: actions[name.value] for name in Action if name.value in actions},
        "not_understood_messages": actions[Action.NOT_UNDERSTOOD.value],
        "learning_queue": len(attendant.learning_queue),
        "llm_calls": 0,
        "_conversations": conversations,  # removed before writing metricas.json
        "_latencies": [t.latency_ms for t in turns],
    }


def transcript(conv: Conversation, kb: KnowledgeBase) -> str:
    lines = [
        f"=== {mask_phone(conv.phone)} | main question: {conv.main_intent} | {conv.outcome} ==="
    ]
    for t in conv.turns:
        lines.append(f"Customer: {t.text}")
        tag = f"{t.action.value}, {t.intent}, {t.confidence:.2f}"
        lines.append(f"Bot [{tag}]: {t.reply or '(silent: with a human)'}")
    return "\n".join(lines)
