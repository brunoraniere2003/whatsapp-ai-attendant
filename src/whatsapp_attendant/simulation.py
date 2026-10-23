"""Seeded simulation of customer conversations, scored against the customer's real question.

Customer messages come from the frozen test split (never seen in training), with typos and filler
added at random. A conversation is `resolved` only when the bot answered the main question
without a handoff (RQ-29); answering a different question is `misrouted`.
"""

from __future__ import annotations

import random
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .config import Settings
from .dialogue import Action, Attendant, HandoffReason, Turn
from .evaluation import Split
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
MAX_TURNS = 8
OUTCOMES = (
    "resolved",
    "requested_handoff",
    "failure_handoff",
    "unrequested_handoff",
    "misrouted",
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


@dataclass
class Conversation:
    phone: str
    main_intent: str
    turns: list[Turn] = field(default_factory=list)
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


def classify_outcome(main_intent: str, turns: list[Turn]) -> str:
    handoff = next((t for t in turns if t.action is Action.HANDOFF), None)
    if handoff is not None:
        if handoff.handoff_reason is HandoffReason.REPEATED_FAILURES:
            return "failure_handoff"
        return "requested_handoff" if main_intent == "human_agent" else "unrequested_handoff"
    answered = {t.intent for t in turns if t.action is Action.ANSWER}
    return "resolved" if main_intent in answered else "misrouted"


def _script(
    rng: random.Random, kb: KnowledgeBase, test: Split, cfg: SimulationConfig
) -> tuple[str, list[str]]:
    """The main intent and the opening messages of one customer."""
    messages: list[str] = []
    if rng.random() < cfg.greeting_rate:
        messages.append(rng.choice(test.phrases["greeting"]))
    if rng.random() < cfg.out_of_scope_rate:
        messages.append(rng.choice(test.phrases["out_of_scope"]))
    main = rng.choices(list(INTENT_WEIGHTS), weights=list(INTENT_WEIGHTS.values()))[0]
    question = rng.choice(test.phrases[main])
    if rng.random() < cfg.typo_rate:
        question = add_typo(question, rng)
    question += rng.choice(SUFFIXES)
    if kb.intent(main).slot == "order_number" and rng.random() < cfg.number_in_first_message_rate:
        question += f", pedido {rng.randint(100000, 999999)}"
    messages.append(question)
    return main, messages


def simulate(
    kb: KnowledgeBase, settings: Settings, test: Split, cfg: SimulationConfig | None = None
) -> dict:
    cfg = cfg or SimulationConfig()
    rng = random.Random(cfg.seed)
    attendant = Attendant(
        kb,
        LocalProvider(kb, settings.engine),
        settings.dialogue,
        switch_threshold=settings.engine.switch_threshold,
    )
    conversations: list[Conversation] = []
    for _ in range(cfg.conversations):
        phone = _phone(rng)
        main, messages = _script(rng, kb, test, cfg)
        has_order = kb.intent(main).slot == "order_number"
        conv = Conversation(phone, main)
        queue = list(messages)
        said_dont_know = rephrased = False
        while queue and len(conv.turns) < MAX_TURNS:
            turn = attendant.handle(phone, queue.pop(0))
            conv.turns.append(turn)
            if turn.action is Action.HANDOFF:
                break
            if turn.action not in (Action.ASK_SLOT, Action.REASK_SLOT):
                continue
            if not has_order:
                # Asked for an order number the customer does not have: they rephrase once.
                if not rephrased:
                    others = [t for t in test.phrases[main] if not messages[-1].startswith(t)]
                    queue.insert(0, rng.choice(others))
                    rephrased = True
            elif not said_dont_know and rng.random() < cfg.dont_know_rate:
                queue.insert(0, rng.choice(DONT_KNOW))
                said_dont_know = True
            else:
                number = rng.randint(100000, 999999)
                queue.insert(0, rng.choice(NUMBER_REPLIES).format(n=number))
        if (
            not any(t.action is Action.HANDOFF for t in conv.turns)
            and rng.random() < cfg.goodbye_rate
        ):
            conv.turns.append(attendant.handle(phone, rng.choice(test.phrases["goodbye"])))
        conv.outcome = classify_outcome(main, conv.turns)
        conversations.append(conv)
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
