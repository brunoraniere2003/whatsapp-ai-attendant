"""Local intent classifier: TF-IDF over words and character trigrams, nearest example by cosine.

Character trigrams make it robust to typos and missing accents ("cade", "boleto vencidoo").
It trains in milliseconds from the knowledge base and needs no network (RQ-8, RQ-11).

A bag of words cannot see negation ("não quero cancelar" and "quero cancelar" share every
content word), so negation is a separate rule over clauses (`negated_words`, RQ-35), and the
answer to a yes or no question is read by `yes_or_no` (RQ-36). Both are pt-BR, like STOPWORDS.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .knowledge import NOT_UNDERSTOOD, normalize

# Function words that appear in almost every intent and only add noise.
# fmt: off
STOPWORDS = frozenset({
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "e", "um", "uma", "me", "meu",
    "minha", "pra", "para", "por", "com", "em", "no", "na", "que", "se", "eu", "ja",
    "voces", "vcs", "qual", "tem", "quero", "preciso", "nao", "ta", "ai", "favor",
})
# Words that negate what follows them ("n" is how "não" is typed in a hurry).
NEGATIONS = frozenset({"nao", "n", "nem", "nunca", "jamais", "nenhum", "nenhuma"})
# Light words a negation skips before reaching the word it negates: "não quero mais cancelar".
NEGATION_SKIP = STOPWORDS | frozenset({
    "mais", "quer", "queria", "gostaria", "vou", "vai", "pode", "posso", "precisa", "consigo",
    "falar", "conversar", "ser", "esse", "essa", "isso", "este", "esta", "isto",
})
# A yes to a confirmation. "pode" is not one: "pode enviar" asks to keep the order.
AFFIRMATIONS = frozenset({
    "sim", "s", "ss", "sss", "isso", "confirmo", "confirma", "confirmar", "confirmado", "claro",
    "positivo", "certo", "certeza", "exato", "ok", "okay", "yes", "uhum", "aham", "beleza",
    "blz", "fechado",
})
NO_WORDS = NEGATIONS | frozenset({"negativo"})
# A negation reaches only the clause it is in: "não quero o produto, quero cancelar".
CLAUSE_BREAK = re.compile(r"[,.;:!?\n()]+|\b(?:mas|porem|entretanto|contudo)\b")
# fmt: on


def _clauses(text: str) -> list[list[str]]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return [words for part in CLAUSE_BREAK.split(plain) if (words := normalize(part).split())]


def negated_words(text: str) -> set[str]:
    """Content words under a negation, clause by clause.

    A negation word negates the first content word after it ("não quero mais cancelar" negates
    "cancelar"); one that closes the clause negates the content word before it ("quero cancelar
    não"). Other content words stay positive: "não gostei, quero cancelar" negates "gostei".
    """
    out: set[str] = set()
    for words in _clauses(text):
        for i, word in enumerate(words):
            if word not in NEGATIONS:
                continue
            ahead = next((w for w in words[i + 1 :] if w not in NEGATION_SKIP), None)
            if ahead is not None and ahead not in NEGATIONS:
                out.add(ahead)
            if i == len(words) - 1 and i > 0:
                behind = next((w for w in reversed(words[:i]) if w not in NEGATION_SKIP), None)
                if behind is not None and behind not in NEGATIONS:
                    out.add(behind)
    return out


def _starts(word: str, terms: Iterable[str]) -> bool:
    return any(word.startswith(term) for term in terms)


def is_negated(text: str, terms: Iterable[str]) -> bool:
    """True when a word starting with one of `terms` is negated in `text`."""
    terms = tuple(terms)
    return bool(terms) and any(_starts(word, terms) for word in negated_words(text))


def yes_or_no(text: str, terms: Iterable[str] = ()) -> bool | None:
    """Answer to a yes or no question: True, False, or None when unclear or contradictory.

    A yes is an affirmation word or one of the intent's own `terms` not negated ("pode
    cancelar"); a no is any negation word. Both, or neither, is unclear.
    """
    terms = tuple(terms)
    words = normalize(text).split()
    negated = negated_words(text)
    no = any(word in NO_WORDS for word in words)
    yes = any(
        word in AFFIRMATIONS or (_starts(word, terms) and word not in negated) for word in words
    )
    if yes != no:
        return yes
    return None


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

    def vector(self, text: str) -> dict[str, float]:
        """Unit TF-IDF vector of `text` with this model's weights: what the model compares."""
        return self._vector(Counter(features(text)))

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(b) < len(a):
            a, b = b, a
        return sum(weight * b[t] for t, weight in a.items() if t in b)

    def scores(self, text: str) -> list[tuple[str, float]]:
        """Best cosine similarity per intent, highest first."""
        query = self.vector(text)
        if not query:
            return []
        best: dict[str, float] = {}
        for label, vec in zip(self.labels, self.vectors, strict=True):
            sim = self.cosine(query, vec)
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
