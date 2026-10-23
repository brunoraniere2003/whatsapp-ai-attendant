import pytest

from whatsapp_attendant.config import Settings
from whatsapp_attendant.evaluation import (
    DatasetError,
    Split,
    evaluate,
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
    assert overlaps(kb, leaky) == ["oi"]


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
    [{"phrases": {"unknown_intent": ["x"]}}, {"other": {}}, {"phrases": ["x"]}],
)
def test_malformed_splits_are_rejected(kb, data):
    with pytest.raises(DatasetError):
        parse_split("bad", data, kb)
