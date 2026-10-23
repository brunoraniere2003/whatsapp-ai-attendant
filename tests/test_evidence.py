import json
import random

import pytest
from conftest import ROOT

from whatsapp_attendant import evidence, report
from whatsapp_attendant.dialogue import Action, HandoffReason, Turn
from whatsapp_attendant.simulation import add_typo, classify_outcome


@pytest.fixture(scope="module")
def built() -> dict:
    return evidence.build()


def test_ca_12_evidence_is_deterministic_and_matches_the_committed_file(built):
    again = evidence.build()
    assert evidence.dumps(built) == evidence.dumps(again)
    committed = (ROOT / "evidencia" / "metricas.json").read_text(encoding="utf-8")
    assert evidence.dumps(built) == committed, "run: python -m whatsapp_attendant evidence"


def test_ca_12_metrics_are_internally_consistent(built):
    sim, test = built["simulation"], built["test"]
    assert sum(sim["outcomes"].values()) == sim["conversations"] == 300
    assert sim["resolution_rate"] == round(sim["outcomes"]["resolved"] / 300, 4)
    assert test["in_scope_accuracy"] == round(test["in_scope_correct"] / test["in_scope_total"], 4)
    assert built["datasets"]["overlapping_phrases"] == 0
    assert built["config"]["confidence_threshold"] == built["threshold_selection"]["chosen"]
    assert sim["llm_calls"] == 0


def _turn(intent: str, action: Action, reason: HandoffReason | None = None) -> Turn:
    return Turn("x", intent, 0.5, action, "r", handoff_reason=reason)


def test_ca_12_a_wrong_answer_is_misrouted_not_resolved():
    assert classify_outcome("invoice_copy", [_turn("order_status", Action.ANSWER)]) == "misrouted"
    assert classify_outcome("invoice_copy", [_turn("invoice_copy", Action.ANSWER)]) == "resolved"
    failure = _turn("not_understood", Action.HANDOFF, HandoffReason.REPEATED_FAILURES)
    assert classify_outcome("order_status", [failure]) == "failure_handoff"
    request = _turn("human_agent", Action.HANDOFF, HandoffReason.CUSTOMER_REQUEST)
    assert classify_outcome("human_agent", [request]) == "requested_handoff"
    assert classify_outcome("order_status", [request]) == "unrequested_handoff"


def test_typos_change_the_text_but_keep_it_readable():
    rng = random.Random(3)
    variants = {add_typo("quero cancelar o pedido", rng) for _ in range(30)}
    assert len(variants) > 3 and all(len(v) >= 20 for v in variants)
    assert add_typo("oi é", random.Random(1)) in {"oi e", "oi é"}


def test_write_creates_every_evidence_file(tmp_path):
    evidence.write(tmp_path, seed=7, conversations=20)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "metricas.json",
        "benchmark.json",
        "report.html",
        "relatorio.html",
        "transcripts.txt",
    }
    assert json.loads((tmp_path / "metricas.json").read_text(encoding="utf-8"))["seed"] == 7
    transcript = (tmp_path / "transcripts.txt").read_text(encoding="utf-8")
    assert "Customer:" in transcript and "5511*" in transcript


def test_reports_use_each_language_and_number_format(built):
    public, convs, kb = evidence.public(built), built["_conversations"], built["_kb"]
    en = report.render(public, convs, kb, "en")
    pt = report.render(public, convs, kb, "pt", view="overview", nav=True)
    rate = built["simulation"]["resolution_rate"] * 100
    assert f"{rate:.1f}%" in en and f"{rate:.1f}%".replace(".", ",") in pt
    assert "Demo case" in en and "Case demonstrativo com dados fictícios." in pt
    assert "Sample conversations" in en and "Exemplos de conversas" not in pt
    with pytest.raises(ValueError):
        report.render(public, convs, kb, "fr")
    with pytest.raises(ValueError):
        report.render(public, convs, kb, "en", view="tiny")


def test_customer_without_an_order_rephrases_once_when_asked_for_one(kb):
    from whatsapp_attendant.config import Settings
    from whatsapp_attendant.evaluation import Split, load_split
    from whatsapp_attendant.simulation import SimulationConfig, simulate

    test = load_split("test", kb)
    tricky = dict(test.phrases)
    tricky["business_hours"] = ("quero cancelar meu pedido", "cadê meu pedido")
    sim = simulate(
        kb, Settings(), Split("tricky", tricky), SimulationConfig(conversations=80, seed=5)
    )
    hours = [c for c in sim["_conversations"] if c.main_intent == "business_hours"]
    assert hours and all(c.outcome != "resolved" for c in hours)
    asked = [c for c in hours if c.turns and c.turns[0].action is Action.ASK_SLOT]
    assert asked and all(len(c.turns) >= 2 for c in asked)


def test_evidence_refuses_leaky_splits(monkeypatch):
    monkeypatch.setattr(evidence, "overlaps", lambda *a: ["oi"])
    with pytest.raises(ValueError, match="overlap"):
        evidence.build(conversations=5)
