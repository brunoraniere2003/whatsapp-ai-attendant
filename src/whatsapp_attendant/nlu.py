"""Local intent classifier: TF-IDF over words and character trigrams, nearest example by cosine.

Character trigrams make it robust to typos and missing accents ("cade", "boleto vencidoo").
It trains in milliseconds from the knowledge base and needs no network (RQ-8, RQ-11).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .knowledge import NOT_UNDERSTOOD

# Function words that appear in almost every intent and only add noise.
# fmt: off
STOPWORDS = frozenset({
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "e", "um", "uma", "me", "meu",
    "minha", "pra", "para", "por", "com", "em", "no", "na", "que", "se", "eu", "ja",
    "voces", "vcs", "qual", "tem", "quero", "preciso", "nao", "ta", "ai", "favor",
})
# fmt: on


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = re.sub(r"[^a-z0-9\s]", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def features(text: str) -> list[str]:
    words = [w for w in normalize(text).split() if w not in STOPWORDS]
    out = [f"w:{w}" for w in words]
    for word in words:
        padded = f" {word} "
        out.extend(f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2))
    return out


@dataclass(frozen=True)
class Prediction:
    """Result of a classification. `best_guess` keeps the top intent even when rejected."""

    intent: str
    confidence: float
    best_guess: str | None = None
    runner_up: str | None = None
    source: str = "local"

    @property
    def understood(self) -> bool:
        return self.intent != NOT_UNDERSTOOD


class TfidfClassifier:
    def __init__(
        self,
        examples: list[tuple[str, str]],
        threshold: float = 0.16,
        char_weight: float = 0.5,
    ) -> None:
        if not examples:
            raise ValueError("the classifier needs at least one example")
        self.threshold = threshold
        self.char_weight = char_weight
        self.labels = [label for _, label in examples]
        docs = [Counter(features(text)) for text, _ in examples]
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(doc.keys())
        n = len(docs)
        self._unseen_idf = math.log(1 + n) + 1
        self.idf = {term: math.log((1 + n) / (1 + count)) + 1 for term, count in df.items()}
        self.vectors = [self._vector(doc) for doc in docs]

    def _vector(self, counts: Counter[str]) -> dict[str, float]:
        vec = {
            term: (1 + math.log(c))
            * self.idf.get(term, self._unseen_idf)
            * (self.char_weight if term.startswith("c:") else 1.0)
            for term, c in counts.items()
        }
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {term: x / norm for term, x in vec.items()}

    def scores(self, text: str) -> list[tuple[str, float]]:
        """Best cosine similarity per intent, highest first."""
        query = self._vector(Counter(features(text)))
        if not query:
            return []
        best: dict[str, float] = {}
        for label, vec in zip(self.labels, self.vectors, strict=True):
            sim = sum(weight * vec[t] for t, weight in query.items() if t in vec)
            if sim > best.get(label, 0.0):
                best[label] = sim
        return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))

    def predict(self, text: str, threshold: float | None = None) -> Prediction:
        limit = self.threshold if threshold is None else threshold
        ranked = self.scores(text)
        if not ranked:
            return Prediction(NOT_UNDERSTOOD, 0.0)
        top, confidence = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else None
        confidence = round(confidence, 4)
        if confidence < limit:
            return Prediction(NOT_UNDERSTOOD, confidence, best_guess=top, runner_up=runner_up)
        return Prediction(top, confidence, best_guess=top, runner_up=runner_up)
