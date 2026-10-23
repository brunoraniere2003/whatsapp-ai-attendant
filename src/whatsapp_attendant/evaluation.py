"""Honest evaluation: dev split to choose the threshold, frozen test split to report (RQ-26, RQ-27).

Metrics treat "out of scope" as a class of its own: an out-of-scope phrase is correct only when
the engine rejects it, and an in-scope phrase that is rejected counts as a miss.

Leakage is measured on what the model sees (ADR-005): two phrases are the same input when their
words, without stopwords, form the same set (order and repetition do not count), or when their
TF-IDF cosine reaches NEAR_DUPLICATE.
"""

from __future__ import annotations

import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from .knowledge import NOT_UNDERSTOOD, KnowledgeBase, bundled_text
from .nlu import STOPWORDS, Prediction, TfidfClassifier, normalize

OUT_OF_SCOPE = "out_of_scope"
NEAR_DUPLICATE = 0.95  # cosine at or above which two phrases are the same model input
THRESHOLD_GRID = tuple(round(0.10 + 0.02 * i, 2) for i in range(26))  # 0.10 to 0.60


class DatasetError(ValueError):
    """An evaluation split is malformed or refers to unknown intents."""


@dataclass(frozen=True)
class Split:
    name: str
    phrases: dict[str, tuple[str, ...]]

    def in_scope(self) -> list[tuple[str, str]]:
        return [
            (t, intent) for intent, ts in self.phrases.items() if intent != OUT_OF_SCOPE for t in ts
        ]

    def out_of_scope(self) -> list[str]:
        return list(self.phrases.get(OUT_OF_SCOPE, ()))

    def __len__(self) -> int:
        return sum(len(ts) for ts in self.phrases.values())


def parse_split(name: str, data: dict, kb: KnowledgeBase) -> Split:
    phrases = data.get("phrases")
    if not isinstance(phrases, dict) or set(data) != {"phrases"}:
        raise DatasetError(f"{name}: expected a single [phrases] table")
    unknown = set(phrases) - set(kb.intent_names) - {OUT_OF_SCOPE}
    if unknown:
        raise DatasetError(f"{name}: unknown intents {sorted(unknown)}")
    for intent, texts in phrases.items():
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise DatasetError(f"{name}: {intent} must be a list of strings")
    clean = {k: tuple(t for t in v if t.strip()) for k, v in phrases.items()}
    return Split(name, clean)


def load_split(name: str, kb: KnowledgeBase) -> Split:
    return parse_split(name, tomllib.loads(bundled_text(f"eval/{name}.toml")), kb)


def fingerprint(text: str) -> frozenset[str]:
    """The words the model keeps, as a set: order and repetition do not change its input."""
    return frozenset(w for w in normalize(text).split() if w not in STOPWORDS)


@dataclass(frozen=True)
class Leak:
    split: str
    text: str
    other: str  # "train" or the name of an earlier split
    other_text: str
    reason: str  # "same words" or "cosine 0.97"

    def __str__(self) -> str:
        return f"{self.split}: {self.text!r} ~ {self.other}: {self.other_text!r} ({self.reason})"


def find_leaks(
    kb: KnowledgeBase,
    *splits: Split,
    limit: float = NEAR_DUPLICATE,
    char_weight: float = 0.5,
) -> list[Leak]:
    """Phrases of each split that are the same model input as a training example or a phrase
    of an earlier split (dev before test). Each leaking phrase is reported once."""
    model = TfidfClassifier(kb.labeled_examples(), char_weight=char_weight)

    def entry(name: str, text: str) -> tuple[str, str, frozenset[str], dict[str, float]]:
        return name, text, fingerprint(text), model.vector(text)

    earlier = [entry("train", text) for text, _ in kb.labeled_examples()]
    leaks: list[Leak] = []
    for split in splits:
        current = [entry(split.name, t) for texts in split.phrases.values() for t in texts]
        for name, text, words, vec in current:
            for other, other_text, other_words, other_vec in earlier:
                if words and words == other_words:
                    reason = "same words"
                elif (sim := model.cosine(vec, other_vec)) >= limit:
                    reason = f"cosine {sim:.2f}"
                else:
                    continue
                leaks.append(Leak(name, text, other, other_text, reason))
                break
        earlier += current
    return leaks


def overlaps(kb: KnowledgeBase, *splits: Split, char_weight: float = 0.5) -> list[str]:
    """Readable list of the leaks; empty when the splits are clean (RQ-26)."""
    return [str(leak) for leak in find_leaks(kb, *splits, char_weight=char_weight)]


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def evaluate(predict: Callable[[str], Prediction], split: Split, kb: KnowledgeBase) -> dict:
    intents = kb.intent_names
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    confusions: Counter[tuple[str, str]] = Counter()
    correct = 0
    in_scope = split.in_scope()
    for text, gold in in_scope:
        got = predict(text).intent
        if got == gold:
            correct += 1
            tp[gold] += 1
            continue
        fn[gold] += 1
        if got != NOT_UNDERSTOOD:
            fp[got] += 1
        confusions[(gold, got)] += 1
    oos = split.out_of_scope()
    rejected = 0
    for text in oos:
        got = predict(text).intent
        if got == NOT_UNDERSTOOD:
            rejected += 1
        else:
            fp[got] += 1
            confusions[(OUT_OF_SCOPE, got)] += 1
    per_intent = {}
    for name in intents:
        precision = _ratio(tp[name], tp[name] + fp[name])
        recall = _ratio(tp[name], tp[name] + fn[name])
        f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
        per_intent[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp[name] + fn[name],
        }
    macro_f1 = round(sum(v["f1"] for v in per_intent.values()) / len(per_intent), 4)
    ordered = sorted(confusions.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "in_scope_total": len(in_scope),
        "in_scope_correct": correct,
        "in_scope_accuracy": _ratio(correct, len(in_scope)),
        "out_of_scope_total": len(oos),
        "out_of_scope_rejected": rejected,
        "out_of_scope_rejection_rate": _ratio(rejected, len(oos)),
        "overall_accuracy": _ratio(correct + rejected, len(in_scope) + len(oos)),
        "macro_f1": macro_f1,
        "per_intent": per_intent,
        "confusions": [[gold, got, n] for (gold, got), n in ordered],
    }


def sweep_thresholds(
    classifier: TfidfClassifier, split: Split, grid: tuple[float, ...] = THRESHOLD_GRID
) -> dict:
    """Overall accuracy on `split` for each threshold; the chosen one is the median of the best."""
    items = [(text, gold) for text, gold in split.in_scope()]
    items += [(text, NOT_UNDERSTOOD) for text in split.out_of_scope()]
    ranked = [(gold, classifier.scores(text)) for text, gold in items]
    curve = []
    for threshold in grid:
        hits = 0
        for gold, scores in ranked:
            top, best = scores[0] if scores else (NOT_UNDERSTOOD, 0.0)
            got = top if round(best, 4) >= threshold else NOT_UNDERSTOOD
            hits += got == gold
        curve.append({"threshold": threshold, "accuracy": _ratio(hits, len(ranked))})
    best_value = max(point["accuracy"] for point in curve)
    best = [point["threshold"] for point in curve if point["accuracy"] == best_value]
    chosen = best[(len(best) - 1) // 2]
    return {
        "split": split.name,
        "grid": [grid[0], grid[-1], round(grid[1] - grid[0], 2)],
        "chosen": chosen,
        "accuracy_at_chosen": best_value,
        "curve": curve,
    }
