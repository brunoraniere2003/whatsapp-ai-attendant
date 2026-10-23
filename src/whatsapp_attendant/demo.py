"""Demo UI (disabled by default): a conversation console and the evaluation dashboard (RQ-30).

The console runs scripted conversations through the same Attendant rules the webhook uses, in a
sandbox that never touches webhook sessions or sends anything. Its message box talks to another
sandbox through `POST /console/api/message`.

The sandboxes use the local engine only, never the LLM layer: the demo answers anyone who can
reach it, and a page view must not cost an API call (RQ-30). The scenarios run once, when the
demo is mounted, and each page is rendered once.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import evidence, report
from .dialogue import Action, Attendant, Session, Turn
from .knowledge import UNSUPPORTED
from .logs import mask_phone
from .providers import LLMFallbackProvider, LocalProvider
from .static import asset

if TYPE_CHECKING:
    from .api import Runtime

MEDIA = "[image]"


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    note: str
    messages: tuple[str, ...]


SCENARIOS = (
    Scenario(
        "order-status",
        "Order status, number asked",
        "Asks for the order number, re-asks once, then answers",
        (
            "oi, boa tarde",
            "cade meu pedido?? ja faz uma semana",
            "não sei onde vejo",
            "é o 482915",
            "valeu!",
        ),
    ),
    Scenario(
        "number-in-message",
        "Number already in the message",
        "Masks the number, classifies, answers at once",
        ("o boleto venceu, pedido 731204", "obrigada"),
    ),
    Scenario(
        "topic-switch",
        "Topic switch to a person",
        "Leaves the pending question and hands off on request",
        ("quero cancelar minha compra", "na verdade quero falar com uma pessoa", "alô?"),
    ),
    Scenario(
        "cancel-confirmation",
        "Cancellation needs a yes",
        "Reuses the number, asks to confirm, keeps the order on a no",
        ("cadê meu pedido 482915?", "quero cancelar", "não, pode enviar"),
    ),
    Scenario(
        "two-failures",
        "Two misunderstandings",
        "Both go to the learning queue, the second hands off",
        ("vocês vendem bicicleta?", "e patinete elétrico, tem?"),
    ),
    Scenario(
        "typos",
        "Typos and abbreviations",
        "Character trigrams survive missing letters and accents",
        ("qro trocar o produto q veio com defeito", "pedido nº 551902"),
    ),
    Scenario(
        "media",
        "Image instead of text",
        "Unsupported types get a polite request for text",
        (MEDIA, "vcs atendem sabado?", "ok obg"),
    ),
)


class ConsoleMessage(BaseModel):
    session: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=1000)


def _phone(index: int) -> str:
    """A number that cannot exist: a Brazilian subscriber number never starts with 0."""
    return f"55110{index:08d}"


def _turn_json(turn: Turn) -> dict:
    return {
        "text": turn.text,
        "reply": turn.reply,
        "intent": turn.intent,
        "confidence": turn.confidence,
        "action": turn.action.value,
        "source": turn.source,
        "handoff_reason": turn.handoff_reason.value if turn.handoff_reason else None,
        "slots": dict(turn.slots),
    }


Results = list[tuple[Scenario, str, list[Turn]]]


def sandbox(rt: Runtime) -> Attendant:
    """An attendant with the runtime's rules and knowledge base and the local engine only."""
    return Attendant(
        rt.kb,
        LocalProvider(rt.kb, rt.settings.engine),
        rt.settings.dialogue,
        switch_threshold=rt.settings.engine.switch_threshold,
    )


def run_scenarios(attendant: Attendant) -> Results:
    results = []
    for index, scenario in enumerate(SCENARIOS, start=1):
        phone = _phone(index)
        turns = [
            attendant.handle_unsupported(phone, "image")
            if m == MEDIA
            else attendant.handle(phone, m)
            for m in scenario.messages
        ]
        results.append((scenario, phone, turns))
    return results


def _e(value: object) -> str:
    return html.escape(str(value))


def _outcome(turns: list[Turn]) -> tuple[str, str]:
    if any(t.action is Action.HANDOFF for t in turns):
        return "Handed to a person", "tag-hand"
    return "Answered by the bot", "tag-ok"


def _bubbles(turns: list[Turn]) -> str:
    out = []
    for turn in turns:
        out.append(f'<div class="b in"><p>{_e(turn.text)}</p></div>')
        if turn.reply is None:
            out.append('<div class="sys">silent: a person has this conversation</div>')
            continue
        meta = f"{turn.intent} · {turn.confidence:.2f} · {turn.action.value}"
        out.append(f'<div class="b out"><p>{_e(turn.reply)}</p><small>{_e(meta)}</small></div>')
        if turn.action is Action.HANDOFF:
            reason = turn.handoff_reason.value if turn.handoff_reason else ""
            out.append(f'<div class="sys">handed off · {_e(reason)}</div>')
    return "".join(out)


def _trace(turns: list[Turn]) -> str:
    rows = []
    for i, turn in enumerate(turns, start=1):
        conf = "" if turn.intent in (UNSUPPORTED, "with_human") else f"{turn.confidence:.2f}"
        action = _e(turn.action.value)
        rows.append(
            f"<tr><td>{i}</td><td>{_e(turn.intent)}</td><td>{conf}</td>"
            f'<td><span class="act act-{action}">{action}</span></td></tr>'
        )
    return "".join(rows)


def _state(session: Session) -> str:
    rows = [
        ("Order number", session.slots.get("order_number", "none")),
        ("Pending question", session.pending_intent or "none"),
        ("Failed turns in a row", session.failed_turns),
        ("Handoff", session.handoff_reason.value if session.handoff_reason else "no"),
    ]
    return "".join(f"<div><span>{_e(k)}</span><b>{_e(v)}</b></div>" for k, v in rows)


def _kb_rows(rt: Runtime) -> str:
    chips = []
    for intent in rt.kb.intents:
        kind = "handoff" if intent.handoff else ("slot" if intent.slot else "answers")
        chips.append(
            f'<span class="k-{kind}">{_e(intent.name)} <b>{len(intent.examples)}</b></span>'
        )
    return "".join(chips)


def render_console(rt: Runtime, selected: str, results: Results, scenarios: Attendant) -> str:
    """The console page for `selected`; `scenarios` is the sandbox that ran `results`."""
    keys = [s.key for s, _, _ in results]
    current = selected if selected in keys else keys[0]
    links = []
    for scenario, _, turns in results:
        label, cls = _outcome(turns)
        on = " on" if scenario.key == current else ""
        links.append(
            f'<a class="{on.strip()}" href="?scenario={scenario.key}"><b>{_e(scenario.title)}</b>'
            f"<small>{_e(scenario.note)}</small><br>"
            f'<span class="tag {cls}">{_e(label)}</span></a>'
        )
    scenario, phone, turns = next(r for r in results if r[0].key == current)
    session = scenarios.session(phone)
    queue = (
        "".join(
            f"<li>{_e(item.text)}<small>{_e(item.phone)} · best guess {_e(item.best_guess)} "
            f"{item.confidence:.2f}</small></li>"
            for item in scenarios.learning_queue
        )
        or "<li>empty</li>"
    )
    examples = len(rt.kb.labeled_examples())
    webhook_llm = isinstance(rt.provider, LLMFallbackProvider)
    llm = "on for the webhook, off in this console" if webhook_llm else "off"
    threshold = rt.settings.engine.confidence_threshold
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conversation console</title><style>{asset("console.css")}</style></head><body>
<div class="top"><div class="logo">W</div>
<h1>AI WhatsApp Attendant <span>· conversation console</span></h1>
<div class="chips"><span class="chip">Local intent engine · threshold {threshold:.2f}</span>
<span class="chip">LLM layer: {llm}</span>
<span class="chip">Knowledge base: {len(rt.kb.intents)} intents, {examples} examples</span>
<span class="chip">Fictional data</span></div></div>
<div class="wrap">
<div class="panel scen"><h2>Scripted scenarios</h2>{"".join(links)}
<p class="note">Each scenario runs through the same Attendant rules the webhook uses, with the
local engine, in a sandbox that sends nothing. Type in the box to start your own conversation.</p>
</div>
<div class="panel chat"><div class="head"><div class="avatar">LE</div><div>
<b>{_e(rt.kb.store_name)} · {_e(scenario.title)}</b>
<small>simulated customer {_e(mask_phone(phone))} · sandbox, nothing is sent</small></div></div>
<div class="msgs" id="msgs">{_bubbles(turns)}</div>
<form id="send"><input name="text" autocomplete="off"
placeholder="Type a customer message in Portuguese, for example: quero a segunda via do boleto">
<button>Send</button></form></div>
<div class="panel side"><h2>Engine trace</h2>
<table><thead><tr><th>#</th><th>Intent</th><th>Conf.</th><th>Action</th></tr></thead>
<tbody id="trace">{_trace(turns)}</tbody></table>
<h2>Session state</h2><div class="state">{_state(session)}</div>
<h2>Learning queue (all scenarios)</h2><ul class="queue">{queue}</ul>
<h2>Knowledge base · examples per intent</h2>
<div class="kb">{_kb_rows(rt)}</div>
<p class="legend"><i class="k-answers"></i>answers <i class="k-slot"></i>asks order number
<i class="k-handoff"></i>hands off</p></div>
</div><script>{asset("console.js")}</script></body></html>"""


def mount(app: FastAPI, rt: Runtime) -> None:
    scenarios = sandbox(rt)
    results = run_scenarios(scenarios)  # once per process
    keys = [s.key for s, _, _ in results]
    pages: dict[str, str] = {}
    chat = sandbox(rt)
    cache: dict[str, dict] = {}

    @app.get("/console", response_class=HTMLResponse, include_in_schema=False)
    def console(scenario: str = "") -> HTMLResponse:
        key = scenario if scenario in keys else keys[0]
        if key not in pages:
            pages[key] = render_console(rt, key, results, scenarios)
        return HTMLResponse(pages[key])

    @app.post("/console/api/message", include_in_schema=False)
    def console_message(body: ConsoleMessage) -> dict:
        return _turn_json(chat.handle(f"demo-{body.session}", body.text))

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(lang: str = "en", view: str = "overview") -> HTMLResponse:
        if lang not in report.TEXT or view not in ("overview", "full"):
            raise HTTPException(status_code=404, detail="unknown language or view")
        if "metrics" not in cache:
            try:
                cache["metrics"] = evidence.build(settings=rt.settings)
            except ValueError as exc:  # e.g. a threshold that is not the dev choice (RQ-27)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        metrics = cache["metrics"]
        page = report.render(
            evidence.public(metrics), metrics["_conversations"], rt.kb, lang, view, nav=True
        )
        return HTMLResponse(page)
