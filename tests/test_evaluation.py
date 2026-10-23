import pytest

from whatsapp_attendant.config import Settings
from whatsapp_attendant.evaluation import (
    NEAR_DUPLICATE,
    DatasetError,
    Split,
    evaluate,
    find_leaks,
    load_split,
    overlaps,
    parse_split,
    sweep_thresholds,
)
from whatsapp_attendant.nlu import Prediction, TfidfClassifier


def test_ca_12_splits_share_no_phrase_with_training_or_each_other(kb):
    dev, test = load_split("dev", kb), load_split("test", kb)
    assert overlaps(kb, dev, test) == []
    assert len(test.in_scope()) >= 100 and len(test.out_of_scope()) >= 10


def test_ca_12_overlap_detection_works(kb):
    leaky = Split("leaky", {"greeting": ("Oi!",)})
    assert overlaps(kb, leaky) == ["leaky: 'Oi!' ~ train: 'oi' (same words)"]


@pytest.mark.parametrize(
    ("phrase", "twin"),
    [
        ("oi oi", "oi"),  # repetition
        ("tchau tchau", "tchau"),
        ("quero cancelar o pedido", "quero cancelar meu pedido"),  # stopwords only
        ("atendente por favor", "preciso de um atendente"),
        ("abrem sábado?", "vocês abrem sábado?"),
        ("horário de atendimento por favor", "qual o horário de atendimento"),
    ],
)
def test_ca_12_leakage_is_measured_on_what_the_model_sees(kb, phrase, twin):
    (leak,) = find_leaks(kb, Split("test", {"greeting": (phrase,)}))
    assert (leak.text, leak.other, leak.other_text, leak.reason) == (
        phrase,
        "train",
        twin,
        "same words",
    )


def test_ca_12_test_phrases_are_checked_against_dev_in_any_word_order(kb):
    dev = Split("dev", {"order_status": ("meu pedido nao chegou ainda",)})
    test = Split("test", {"order_status": ("meu pedido ainda nao chegou",)})
    assert overlaps(kb, dev, test) == [
        "test: 'meu pedido ainda nao chegou' ~ dev: 'meu pedido nao chegou ainda' (same words)"
    ]
    assert overlaps(kb, test) == []  # dev was the twin, not training


def test_ca_12_near_duplicates_are_caught_by_cosine_and_paraphrases_pass(kb):
    assert NEAR_DUPLICATE == 0.95
    split = Split("test", {"invoice_copy": ("segunda via da faturas",)})
    assert find_leaks(kb, split) == []  # cosine 0.77 with "segunda via da fatura"
    (leak,) = find_leaks(kb, split, limit=0.7)
    assert leak.other_text == "segunda via da fatura" and leak.reason.startswith("cosine 0.7")
    paraphrase = Split("test", {"order_status": ("a transportadora sumiu com a encomenda",)})
    assert overlaps(kb, paraphrase) == []


def test_ca_12_default_threshold_is_the_one_chosen_on_dev(kb):
    clf = TfidfClassifier(kb.labeled_examples())
    chosen = sweep_thresholds(clf, load_split("dev", kb))["chosen"]
    assert Settings().engine.confidence_threshold == chosen


def test_sweep_picks_the_median_of_the_best_thresholds():
    clf = TfidfClassifier(
        [("boleto atrasado", "invoice_copy"), ("pedido atrasado", "order_status")]
    )
    split = Split("s", {"invoice_copy": ("boleto",), "out_of_scope": ("bicicleta",)})
    result = sweep_thresholds(clf, split, grid=(0.1, 0.2, 0.3))
    assert [p["accuracy"] for p in result["curve"]] == [1.0, 1.0, 1.0]
    assert result["chosen"] == 0.2 and result["grid"] == [0.1, 0.3, 0.1]


def test_evaluate_counts_misses_false_positives_and_rejections(kb):
    answers = {"a": "greeting", "b": "not_understood", "c": "goodbye", "d": "not_understood"}
    split = Split("t", {"greeting": ("a", "b"), "goodbye": ("x",), "out_of_scope": ("c", "d")})
    answers["x"] = "goodbye"
    result = evaluate(lambda t: Prediction(answers[t], 0.5), split, kb)
    assert (result["in_scope_correct"], result["in_scope_total"]) == (2, 3)
    assert (result["out_of_scope_rejected"], result["out_of_scope_total"]) == (1, 2)
    assert result["per_intent"]["greeting"] == {
        "precision": 1.0,
        "recall": 0.5,
        "f1": 0.6667,
        "support": 2,
    }
    assert result["per_intent"]["goodbye"]["precision"] == 0.5
    assert ["greeting", "not_understood", 1] in result["confusions"]
    assert ["out_of_scope", "goodbye", 1] in result["confusions"]


@pytest.mark.parametrize(
    "data",
    [
        {"phrases": {"unknown_intent": ["x"]}},
        {"other": {}},
        {"phrases": ["x"]},
        {"phrases": {"greeting": "oi tudo bem"}},
        {"phrases": {"greeting": ["oi", 3]}},
    ],
)
def test_malformed_splits_are_rejected(kb, data):
    with pytest.raises(DatasetError):
        parse_split("bad", data, kb)
