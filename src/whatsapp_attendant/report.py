"""Evaluation report (HTML) in English or Brazilian Portuguese, built from metricas.json.

The same renderer feeds `evidencia/report.html`, `evidencia/relatorio.html` and the `/dashboard`
page of the demo UI. Charts are inline SVG with native hover titles and a table view beside them.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

from .dialogue import Action
from .knowledge import KnowledgeBase
from .simulation import OUTCOMES, Conversation
from .static import asset

# Reference palette, categorical slots in fixed order (light mode); the last one, neutral grey,
# is for "abandoned", which is neither a success nor a wrong answer.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#8c96a3")

INTENT_NAMES = {
    "en": {
        "greeting": "Greeting",
        "order_status": "Order status",
        "invoice_copy": "Invoice or payment slip copy",
        "payment_status": "Payment confirmation",
        "return_exchange": "Return or exchange",
        "cancel_order": "Order cancellation",
        "business_hours": "Business hours",
        "human_agent": "Talk to a person",
        "goodbye": "Goodbye",
        "not_understood": "Not understood",
        "out_of_scope": "Out of scope",
        "with_human": "With a human",
        "unsupported": "Unsupported type",
    },
    "pt": {
        "greeting": "Saudação",
        "order_status": "Status do pedido",
        "invoice_copy": "Segunda via de boleto ou nota fiscal",
        "payment_status": "Confirmação de pagamento",
        "return_exchange": "Troca ou devolução",
        "cancel_order": "Cancelamento de pedido",
        "business_hours": "Horário de atendimento",
        "human_agent": "Falar com uma pessoa",
        "goodbye": "Encerramento",
        "not_understood": "Não entendida",
        "out_of_scope": "Fora do escopo",
        "with_human": "Com atendente",
        "unsupported": "Tipo não suportado",
    },
}

TEXT = {
    "en": {
        "lang": "en",
        "title": "AI WhatsApp Attendant",
        "kicker": "Evaluation report",
        "sub": (
            "Demo case with fictional data. Seed {seed}, {conv} simulated conversations, "
            "intent accuracy measured on {test} held-out phrases that repeat no training or dev "
            "phrase."
        ),
        "k_resolved": "conversations resolved with the right answer",
        "k_resolved_d": "{n} of {total}, no human involved",
        "k_accuracy": "intent accuracy on held-out phrases",
        "k_accuracy_d": "{n} of {total} test phrases, macro F1 {f1}",
        "k_handoff": "handed to a human",
        "k_handoff_d": "{req} on request, {fail} after {max} failed turns",
        "k_oos": "off-topic messages rejected",
        "k_oos_d": "{n} of {total} instead of a wrong answer",
        "outcomes_t": "Outcome of the {total} simulated conversations",
        "outcomes_s": (
            "Resolved means the bot answered the customer's real question and gave no wrong "
            "answer on the way."
        ),
        "flow": [
            ("customer messages", "{messages}", "{per} per conversation"),
            ("order numbers asked", "{asked}", "{reasked} asked again after a wrong reply"),
            ("not understood", "{nu}", "{queue} queued for the knowledge base"),
            ("LLM calls", "{llm}", "the optional second layer was off in this run"),
        ],
        "f1_t": "F1 per intent on the test split",
        "f1_s": "Test phrases are typed like customers type: no accents, slang, typos.",
        "outcome": "Outcome",
        "count": "Conversations",
        "share": "Share",
        "o_resolved": "Resolved with the right answer",
        "o_requested_handoff": "Handed off on request",
        "o_failure_handoff": "Handed off after failed turns",
        "o_unrequested_handoff": "Handed off without a request",
        "o_misrouted": "Wrong answer or wrong flow",
        "o_abandoned": "Rejected, then the customer left",
        "intent": "Intent",
        "precision": "Precision",
        "recall": "Recall",
        "support": "Phrases",
        "sweep_t": "Confidence threshold chosen on the dev split",
        "sweep_s": (
            "Accuracy on the {n} dev phrases for each threshold. The median of the best "
            "thresholds ({chosen}) became the default; the test split was not used."
        ),
        "chosen": "chosen",
        "nav": ("Overview", "Full report", "Português", "pt"),
        "threshold": "threshold",
        "accuracy": "accuracy",
        "conf_t": "Most frequent mistakes on the test split",
        "real": "Real intent",
        "got": "Bot understood",
        "times": "Times",
        "data_t": "Data and method",
        "data_rows": [
            ("Intents in the knowledge base", "{intents}"),
            ("Training examples (knowledge base)", "{train}"),
            ("Dev split (threshold only)", "{dev_in} in scope, {dev_oos} off topic"),
            ("Test split (reported numbers)", "{test_in} in scope, {test_oos} off topic"),
            ("Leaked phrases (same words, or cosine of {leak} or more)", "{overlap}"),
            ("Customer messages simulated", "{messages}"),
            ("Messages queued for learning", "{queue}"),
            ("LLM calls in this run", "{llm}"),
        ],
        "method": [
            "The classifier learns only from the knowledge base examples.",
            "The dev split chooses the confidence threshold; the test split was frozen "
            "and committed before any evaluation code existed, and has only lost phrases since.",
            "No test phrase is the same model input as a training or dev phrase: the same "
            "words once stopwords are dropped, in any order, or a cosine of {leak} or more, "
            "count as a leak and were removed.",
            "Simulated customers draw their messages from the test split and add typos, "
            "filler words and order numbers at random, with a fixed seed. They rephrase once "
            "when rejected and answer the cancellation question honestly.",
            "A conversation counts as resolved only when the bot answered the main question and "
            "gave no wrong answer; a wrong answer is a failure even if the right one came later.",
        ],
        "samples_t": "Sample conversations",
        "customer": "Customer",
        "bot": "Bot",
        "silent": "(silent: a person has the conversation)",
        "footer": (
            "Demo case: fictional store, customers, phones and orders. No message was sent to a "
            "real person. Generated by python -m whatsapp_attendant evidence."
        ),
    },
    "pt": {
        "lang": "pt-BR",
        "title": "Atendente de WhatsApp com IA",
        "kicker": "Relatório de avaliação",
        "sub": (
            "Case demonstrativo com dados fictícios. Semente {seed}, {conv} conversas simuladas, "
            "acerto de intenção medido em {test} frases de teste que não repetem nenhuma frase de "
            "treino ou de desenvolvimento."
        ),
        "k_resolved": "das conversas resolvidas com a resposta certa",
        "k_resolved_d": "{n} de {total}, sem atendente",
        "k_accuracy": "de acerto de intenção nas frases de teste",
        "k_accuracy_d": "{n} de {total} frases de teste, F1 macro {f1}",
        "k_handoff": "transferidas para um atendente",
        "k_handoff_d": "{req} a pedido, {fail} depois de {max} falhas seguidas",
        "k_oos": "das mensagens fora do assunto recusadas",
        "k_oos_d": "{n} de {total}, em vez de uma resposta errada",
        "outcomes_t": "Resultado das {total} conversas simuladas",
        "outcomes_s": (
            "Resolvida significa que o robô respondeu a dúvida real do cliente sem dar nenhuma "
            "resposta errada no caminho."
        ),
        "flow": [
            ("mensagens de clientes", "{messages}", "{per} por conversa"),
            (
                "pedidos de número do pedido",
                "{asked}",
                "{reasked} repetidos após resposta inválida",
            ),
            ("não entendidas", "{nu}", "{queue} na fila para a base de conhecimento"),
            (
                "chamadas ao modelo de linguagem",
                "{llm}",
                "a segunda camada opcional estava desligada",
            ),
        ],
        "f1_t": "F1 por intenção no conjunto de teste",
        "f1_s": "As frases de teste imitam o cliente real: sem acento, gíria e erro de digitação.",
        "outcome": "Resultado",
        "count": "Conversas",
        "share": "Parcela",
        "o_resolved": "Resolvida com a resposta certa",
        "o_requested_handoff": "Transferida a pedido",
        "o_failure_handoff": "Transferida depois de falhas",
        "o_unrequested_handoff": "Transferida sem pedido",
        "o_misrouted": "Resposta ou fluxo errado",
        "o_abandoned": "Recusada, e o cliente desistiu",
        "intent": "Intenção",
        "precision": "Precisão",
        "recall": "Revocação",
        "support": "Frases",
        "sweep_t": "Limiar de confiança escolhido no conjunto de desenvolvimento",
        "sweep_s": (
            "Acerto nas {n} frases de desenvolvimento para cada limiar. A mediana dos melhores "
            "limiares ({chosen}) virou o padrão; o conjunto de teste não foi usado."
        ),
        "chosen": "escolhido",
        "nav": ("Visão geral", "Relatório completo", "English", "en"),
        "threshold": "limiar",
        "accuracy": "acerto",
        "conf_t": "Erros mais frequentes no conjunto de teste",
        "real": "Intenção real",
        "got": "O robô entendeu",
        "times": "Vezes",
        "data_t": "Dados e método",
        "data_rows": [
            ("Intenções na base de conhecimento", "{intents}"),
            ("Exemplos de treino (base de conhecimento)", "{train}"),
            ("Desenvolvimento (só o limiar)", "{dev_in} no escopo, {dev_oos} fora do assunto"),
            ("Teste (números do relatório)", "{test_in} no escopo, {test_oos} fora do assunto"),
            ("Frases vazadas (mesmas palavras, ou cosseno de {leak} ou mais)", "{overlap}"),
            ("Mensagens de clientes simuladas", "{messages}"),
            ("Mensagens na fila de aprendizado", "{queue}"),
            ("Chamadas ao modelo de linguagem", "{llm}"),
        ],
        "method": [
            "O classificador aprende só com os exemplos da base de conhecimento.",
            "O conjunto de desenvolvimento escolhe o limiar; o de teste foi congelado e versionado "
            "antes de existir qualquer código de avaliação, e desde então só perdeu frases.",
            "Nenhuma frase de teste é a mesma entrada do modelo que uma frase de treino ou de "
            "desenvolvimento: as mesmas palavras sem as stopwords, em qualquer ordem, ou um "
            "cosseno de {leak} ou mais, contam como vazamento e foram retiradas.",
            "Os clientes simulados usam frases do conjunto de teste, com erros de digitação, "
            "palavras soltas e números de pedido sorteados com semente fixa. Eles reformulam uma "
            "vez quando recusados e respondem com sinceridade à pergunta de cancelamento.",
            "A conversa só conta como resolvida quando o robô respondeu a dúvida principal sem dar "
            "resposta errada; uma resposta errada é falha mesmo que a certa venha depois.",
        ],
        "samples_t": "Exemplos de conversas simuladas",
        "customer": "Cliente",
        "bot": "Robô",
        "silent": "(em silêncio: um atendente assumiu a conversa)",
        "footer": (
            "Case demonstrativo: loja, clientes, telefones e pedidos fictícios. Nenhuma mensagem "
            "foi enviada a uma pessoa real. Gerado por python -m whatsapp_attendant evidence."
        ),
    },
}


def fmt_pct(value: float, lang: str, digits: int = 1) -> str:
    text = f"{value * 100:.{digits}f}%"
    return text.replace(".", ",") if lang == "pt" else text


def fmt_num(value: float, lang: str, digits: int = 2) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if lang == "pt" else text


def _e(value: object) -> str:
    return html.escape(str(value))


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Horizontal bar, square at the baseline and rounded at the data end."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (
        f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
        f"a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z"
    )


def _f1_chart(per_intent: dict, lang: str, row_h: int = 33) -> str:
    names = INTENT_NAMES[lang]
    rows = sorted(per_intent.items(), key=lambda kv: (-kv[1]["f1"], kv[0]))
    label_w, bar_w, bar_h = 250, 330, 16
    height = row_h * len(rows) + 26
    parts = [
        f'<svg viewBox="0 0 {label_w + bar_w + 60} {height}" role="img" class="chart" '
        f'aria-label="{_e(TEXT[lang]["f1_t"])}">'
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = label_w + bar_w * tick
        parts.append(
            f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{height - 22}" class="grid"/>'
            f'<text x="{x:.1f}" y="{height - 6}" class="tick" text-anchor="middle">'
            f"{fmt_num(tick, lang, 2)}</text>"
        )
    for i, (name, row) in enumerate(rows):
        y = i * row_h + 8
        w = bar_w * row["f1"]
        tip = (
            f"{names.get(name, name)}: F1 {fmt_num(row['f1'], lang)}, "
            f"{TEXT[lang]['precision']} {fmt_num(row['precision'], lang)}, "
            f"{TEXT[lang]['recall']} {fmt_num(row['recall'], lang)}"
        )
        parts.append(
            f"<g><title>{_e(tip)}</title>"
            f'<text x="{label_w - 12}" y="{y + 13}" class="label" text-anchor="end">'
            f"{_e(names.get(name, name))}</text>"
            f'<path d="{_bar_path(label_w, y, w, bar_h)}" fill="{SERIES[0]}"/>'
            f'<text x="{label_w + w + 8:.1f}" y="{y + 13}" class="value">'
            f"{fmt_num(row['f1'], lang)}</text></g>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _outcome_chart(outcomes: dict, total: int, lang: str) -> str:
    t = TEXT[lang]
    width, height, gap = 700, 34, 2
    visible = [(name, outcomes[name], SERIES[i]) for i, name in enumerate(OUTCOMES)]
    nonzero = [v for v in visible if v[1] > 0]
    usable = width - gap * (len(nonzero) - 1)
    parts = [
        f'<svg viewBox="0 0 {width} {height + 30}" role="img" class="chart" '
        f'aria-label="{_e(t["outcomes_t"].format(total=total))}">'
    ]
    x = 0.0
    for index, (name, count, color) in enumerate(nonzero):
        w = usable * count / total
        first, last = index == 0, index == len(nonzero) - 1
        r = 4
        if first and last:
            shape = f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" rx="{r}"/>'
        elif first:
            shape = (
                f'<path d="M{x + r:.1f},0h{w - r:.1f}v{height}h-{w - r:.1f}'
                f'a{r},{r} 0 0 1 -{r},-{r}v-{height - 2 * r}a{r},{r} 0 0 1 {r},-{r}z"/>'
            )
        elif last:
            shape = f'<path d="{_bar_path(x, 0, w, height, r)}"/>'
        else:
            shape = f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}"/>'
        share = fmt_pct(count / total, lang)
        tip = f"{t['o_' + name]}: {count} ({share})"
        label = ""
        if w >= 56:
            label = (
                f'<text x="{x + w / 2:.1f}" y="{height + 20}" class="value" '
                f'text-anchor="middle">{share}</text>'
            )
        parts.append(f'<g fill="{color}"><title>{_e(tip)}</title>{shape}</g>{label}')
        x += w + gap
    parts.append("</svg>")
    legend = "".join(
        f'<li><span class="sw" style="background:{color}"></span>{_e(t["o_" + name])}'
        f'<b>{count}</b><span class="muted">{fmt_pct(count / total, lang)}</span></li>'
        for name, count, color in visible
    )
    return "".join(parts) + f'<ul class="legend">{legend}</ul>'


def _sweep_chart(selection: dict, lang: str, h: int = 230) -> str:
    t = TEXT[lang]
    curve = selection["curve"]
    w, left, bottom, top = 700, 56, 34, 14
    lo_x, hi_x = curve[0]["threshold"], curve[-1]["threshold"]
    lo_y, hi_y = 0.5, 1.0

    def px(v: float) -> float:
        return left + (w - left - 16) * (v - lo_x) / (hi_x - lo_x)

    def py(v: float) -> float:
        return top + (h - top - bottom) * (hi_y - max(lo_y, v)) / (hi_y - lo_y)

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" class="chart" aria-label="{_e(t["sweep_t"])}">'
    ]
    for tick in (0.5, 0.75, 1.0) if h < 200 else (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        parts.append(
            f'<line x1="{left}" y1="{py(tick):.1f}" x2="{w - 16}" y2="{py(tick):.1f}" '
            'class="grid"/>'
            f'<text x="{left - 8}" y="{py(tick) + 4:.1f}" class="tick" text-anchor="end">'
            f"{fmt_pct(tick, lang, 0)}</text>"
        )
    for tick in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        parts.append(
            f'<text x="{px(tick):.1f}" y="{h - 12}" class="tick" text-anchor="middle">'
            f"{fmt_num(tick, lang)}</text>"
        )
    points = " ".join(f"{px(p['threshold']):.1f},{py(p['accuracy']):.1f}" for p in curve)
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="{SERIES[0]}" stroke-width="2" '
        'stroke-linejoin="round"/>'
    )
    for p in curve:
        tip = f"{t['threshold']} {fmt_num(p['threshold'], lang)}: {fmt_pct(p['accuracy'], lang)}"
        parts.append(
            f'<circle cx="{px(p["threshold"]):.1f}" cy="{py(p["accuracy"]):.1f}" r="9" '
            f'fill="transparent"><title>{_e(tip)}</title></circle>'
        )
    cx, cy = px(selection["chosen"]), py(selection["accuracy_at_chosen"])
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{SERIES[0]}" stroke="#fff" '
        'stroke-width="2"/>'
        f'<text x="{cx + 10:.1f}" y="{cy - 10:.1f}" class="value">{t["chosen"]} '
        f"{fmt_num(selection['chosen'], lang)} · {fmt_pct(selection['accuracy_at_chosen'], lang)}"
        "</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _flow(sim: dict, lang: str) -> str:
    actions = sim["actions"]
    fields = {
        "messages": sim["customer_messages"],
        "per": fmt_num(sim["messages_per_conversation"], lang),
        "asked": actions.get("ask_slot", 0),
        "reasked": actions.get("reask_slot", 0),
        "nu": sim["not_understood_messages"],
        "queue": sim["learning_queue"],
        "llm": sim["llm_calls"],
    }
    return "".join(
        f"<div><b>{_e(v.format(**fields))}</b><span>{_e(label)}</span>"
        f"<small>{_e(detail.format(**fields))}</small></div>"
        for label, v, detail in TEXT[lang]["flow"]
    )


def _table(head: Iterable[str], rows: Iterable[Iterable[object]], cls: str = "") -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def _samples(conversations: list[Conversation], kb: KnowledgeBase, lang: str) -> str:
    t, names = TEXT[lang], INTENT_NAMES[lang]
    picked: list[Conversation] = []
    seen: set[str] = set()
    for conv in conversations:  # the first conversation of each outcome, in simulation order
        if conv.outcome not in seen:
            seen.add(conv.outcome)
            picked.append(conv)
    blocks = []
    for conv in picked:
        lines = []
        for turn in conv.turns:
            reply = turn.reply if turn.reply is not None else t["silent"]
            tag = f"{names.get(turn.intent, turn.intent)} · {fmt_num(turn.confidence, lang)}"
            lines.append(
                f'<div class="msg in"><span>{_e(turn.text)}</span></div>'
                f'<div class="msg out"><span>{_e(reply)}</span><small>{_e(tag)}</small></div>'
            )
            if turn.action is Action.HANDOFF:
                break
        title = f"{names.get(conv.main_intent, conv.main_intent)}: {t['o_' + conv.outcome]}"
        blocks.append(f'<div class="sample"><h4>{_e(title)}</h4>{"".join(lines)}</div>')
    return "".join(blocks)


def _nav(lang: str, view: str) -> str:
    overview, full, other, other_lang = TEXT[lang]["nav"]
    links = [
        (overview, f"?lang={lang}&view=overview", view == "overview"),
        (full, f"?lang={lang}&view=full", view == "full"),
        (other, f"?lang={other_lang}&view={view}", False),
    ]
    items = "".join(
        f'<a href="{href}" class="{"on" if on else ""}">{_e(label)}</a>'
        for label, href, on in links
    )
    return f'<nav class="tabs">{items}</nav>'


def render(
    metrics: dict,
    conversations: list[Conversation],
    kb: KnowledgeBase,
    lang: str = "en",
    view: str = "full",
    nav: bool = False,
) -> str:
    """HTML report for `lang` ("en" or "pt").

    `view="full"` is the whole report; `view="overview"` fits one 1600x900 screen (dashboard).
    `nav` adds the dashboard links between views and languages.
    """
    if lang not in TEXT:
        raise ValueError(f"unsupported language: {lang}")
    if view not in ("full", "overview"):
        raise ValueError(f"unsupported view: {view}")
    overview = view == "overview"
    t, names = TEXT[lang], INTENT_NAMES[lang]
    sim, test, data = metrics["simulation"], metrics["test"], metrics["datasets"]
    total = sim["conversations"]
    out = sim["outcomes"]
    kpis = [
        (
            fmt_pct(sim["resolution_rate"], lang),
            t["k_resolved"],
            t["k_resolved_d"].format(n=out["resolved"], total=total),
        ),
        (
            fmt_pct(test["in_scope_accuracy"], lang),
            t["k_accuracy"],
            t["k_accuracy_d"].format(
                n=test["in_scope_correct"],
                total=test["in_scope_total"],
                f1=fmt_num(test["macro_f1"], lang),
            ),
        ),
        (
            fmt_pct(sim["handoff_rate"], lang),
            t["k_handoff"],
            t["k_handoff_d"].format(
                req=out["requested_handoff"],
                fail=out["failure_handoff"],
                max=metrics["config"]["max_failed_turns"],
            ),
        ),
        (
            fmt_pct(test["out_of_scope_rejection_rate"], lang),
            t["k_oos"],
            t["k_oos_d"].format(n=test["out_of_scope_rejected"], total=test["out_of_scope_total"]),
        ),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><b>{_e(v)}</b><span>{_e(label)}</span><small>{_e(d)}</small></div>'
        for v, label, d in kpis
    )
    selection = metrics["threshold_selection"]
    dev_n = data["dev_in_scope"] + data["dev_out_of_scope"]
    per_intent_rows = [
        (
            names.get(name, name),
            fmt_num(row["precision"], lang),
            fmt_num(row["recall"], lang),
            fmt_num(row["f1"], lang),
            row["support"],
        )
        for name, row in test["per_intent"].items()
    ]
    top = 4 if overview else 8
    confusion_rows = [(names.get(a, a), names.get(b, b), n) for a, b, n in test["confusions"][:top]]
    fields = {
        "intents": data["intents"],
        "train": data["train_examples"],
        "dev_in": data["dev_in_scope"],
        "dev_oos": data["dev_out_of_scope"],
        "test_in": data["test_in_scope"],
        "test_oos": data["test_out_of_scope"],
        "overlap": data["overlapping_phrases"],
        "messages": sim["customer_messages"],
        "queue": sim["learning_queue"],
        "llm": sim["llm_calls"],
        "leak": fmt_num(metrics["config"]["leakage_cosine"], lang),
    }
    data_rows = [
        (label.format(**fields), value.format(**fields)) for label, value in t["data_rows"]
    ]
    test_phrases = data["test_in_scope"] + data["test_out_of_scope"]
    method = "".join(f"<li>{_e(m.format(**fields))}</li>" for m in t["method"])
    details = f"""
<h2>{_e(t["f1_t"])}</h2>
{_table((t["intent"], t["precision"], t["recall"], "F1", t["support"]), per_intent_rows)}
<h2>{_e(t["data_t"])}</h2>
<section class="grid2"><div>{_table(("", ""), data_rows, "kv")}</div>
<div><ul class="method">{method}</ul></div></section>
<h2>{_e(t["samples_t"])}</h2>
<section class="samples">{_samples(conversations, kb, lang)}</section>
<footer>{_e(t["footer"])}</footer>"""
    sweep_text = t["sweep_s"].format(n=dev_n, chosen=fmt_num(selection["chosen"], lang))
    return f"""<!doctype html>
<html lang="{t["lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(t["title"])}: {_e(t["kicker"])}</title><style>{asset("report.css")}</style></head>
<body class="{view}">
<header><div class="htext"><div class="kicker">{_e(t["kicker"])}</div><h1>{_e(t["title"])}</h1>
<p>{_e(t["sub"].format(seed=metrics["seed"], conv=total, test=test_phrases))}</p></div>
{_nav(lang, view) if nav else ""}</header>
<main>
<section class="kpis">{kpi_html}</section>
<section class="grid2">
<div class="card"><h3>{_e(t["outcomes_t"].format(total=total))}</h3>
<p class="s">{_e(t["outcomes_s"])}</p>{_outcome_chart(out, total, lang)}
<div class="flow">{_flow(sim, lang)}</div></div>
<div class="card"><h3>{_e(t["f1_t"])}</h3><p class="s">{_e(t["f1_s"])}</p>
{_f1_chart(test["per_intent"], lang, 29 if overview else 33)}</div>
</section>
<section class="grid2">
<div class="card"><h3>{_e(t["sweep_t"])}</h3>
<p class="s">{_e(sweep_text)}</p>
{_sweep_chart(selection, lang, 116 if overview else 230)}</div>
<div class="card"><h3>{_e(t["conf_t"])}</h3>
{_table((t["real"], t["got"], t["times"]), confusion_rows)}</div>
</section>{"" if overview else details}
</main></body></html>
"""
