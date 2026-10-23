"""One command builds every piece of evidence from a clean, seeded run (RQ-28).

`evidencia/metricas.json` is deterministic: no timings, no dates. Timings, which depend on the
machine, go to `evidencia/benchmark.json`.
"""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path

from . import __version__, report
from .config import Settings
from .evaluation import NEAR_DUPLICATE, evaluate, load_split, overlaps, sweep_thresholds
from .knowledge import KnowledgeBase, load_knowledge_base
from .metrics import percentile
from .nlu import TfidfClassifier
from .simulation import SimulationConfig, simulate, transcript

SCHEMA_VERSION = 1
TRANSCRIPTS = 40


def _digits(kb: KnowledgeBase) -> int:
    match = re.search(r"\\d\{(\d+)\}", kb.slots["order_number"].pattern.pattern)
    return int(match.group(1)) if match else 0


def _summary(result: dict) -> dict:
    keys = (
        "in_scope_total",
        "in_scope_correct",
        "in_scope_accuracy",
        "out_of_scope_total",
        "out_of_scope_rejected",
        "out_of_scope_rejection_rate",
        "overall_accuracy",
        "macro_f1",
    )
    return {k: result[k] for k in keys}


def build(seed: int = 42, conversations: int = 300, settings: Settings | None = None) -> dict:
    """Metrics plus private keys (prefixed with `_`) used for the reports and transcripts."""
    settings = settings or Settings()
    kb = load_knowledge_base(settings.knowledge_base)
    dev, test = load_split("dev", kb), load_split("test", kb)
    leaks = overlaps(kb, dev, test, char_weight=settings.engine.char_ngram_weight)
    if leaks:
        raise ValueError(f"evaluation splits overlap with training or each other: {leaks}")
    classifier = TfidfClassifier(
        kb.labeled_examples(),
        threshold=settings.engine.confidence_threshold,
        char_weight=settings.engine.char_ngram_weight,
    )
    selection = sweep_thresholds(classifier, dev)
    if selection["chosen"] != settings.engine.confidence_threshold:  # RQ-27
        raise ValueError(
            f"configured confidence threshold {settings.engine.confidence_threshold} is not the "
            f"one chosen on the dev split ({selection['chosen']}): update config.py and "
            "config.example.toml"
        )
    dev_result = evaluate(classifier.predict, dev, kb)
    test_result = evaluate(classifier.predict, test, kb)
    sim = simulate(kb, settings, test, SimulationConfig(conversations=conversations, seed=seed))
    public_sim = {k: v for k, v in sim.items() if not k.startswith("_")}
    impatient = simulate(
        kb,
        settings,
        test,
        SimulationConfig(conversations=conversations, seed=seed, rephrase_after_miss=False),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "project": "whatsapp-ai-attendant",
        "version": __version__,
        "seed": seed,
        "data": "fictional store, simulated customers; Brazilian Portuguese",
        "config": {
            "confidence_threshold": settings.engine.confidence_threshold,
            "switch_threshold": settings.engine.switch_threshold,
            "max_failed_turns": settings.dialogue.max_failed_turns,
            "order_number_digits": _digits(kb),
            "leakage_cosine": NEAR_DUPLICATE,
            "llm_enabled": False,
        },
        "datasets": {
            "intents": len(kb.intents),
            "train_examples": len(kb.labeled_examples()),
            "dev_in_scope": dev_result["in_scope_total"],
            "dev_out_of_scope": dev_result["out_of_scope_total"],
            "test_in_scope": test_result["in_scope_total"],
            "test_out_of_scope": test_result["out_of_scope_total"],
            "overlapping_phrases": len(leaks),
        },
        "threshold_selection": selection,
        "dev": _summary(dev_result),
        "test": test_result,
        "simulation": public_sim,
        # Same seed, customers who never rephrase after a rejection or a wrong confirmation.
        "sensitivity": {
            "without_rephrase_after_miss": {
                "resolution_rate": impatient["resolution_rate"],
                "outcomes": impatient["outcomes"],
            }
        },
        "_conversations": sim["_conversations"],
        "_latencies": sim["_latencies"],
        "_kb": kb,
    }


def public(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if not k.startswith("_")}


def dumps(metrics: dict) -> str:
    return json.dumps(public(metrics), ensure_ascii=False, indent=2) + "\n"


def write(out_dir: str | Path = "evidencia", seed: int = 42, conversations: int = 300) -> dict:
    """Write metricas.json, benchmark.json, the two reports and the transcripts."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    metrics = build(seed=seed, conversations=conversations)
    (out / "metricas.json").write_text(dumps(metrics), encoding="utf-8", newline="\n")
    latencies = metrics["_latencies"]
    benchmark = {
        "note": "machine dependent; not used in the cards",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "messages": len(latencies),
        "latency_p50_ms": round(percentile(latencies, 50), 3),
        "latency_p95_ms": round(percentile(latencies, 95), 3),
        "latency_max_ms": round(max(latencies), 3) if latencies else 0.0,
    }
    (out / "benchmark.json").write_text(
        json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    kb = metrics["_kb"]
    for lang, name in (("en", "report.html"), ("pt", "relatorio.html")):
        html = report.render(public(metrics), metrics["_conversations"], kb, lang)
        (out / name).write_text(html, encoding="utf-8", newline="\n")
    lines = [transcript(c, kb) for c in metrics["_conversations"][:TRANSCRIPTS]]
    (out / "transcripts.txt").write_text(
        "Simulated conversations (fictional customers, phones masked).\n\n"
        + "\n\n".join(lines)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return metrics
