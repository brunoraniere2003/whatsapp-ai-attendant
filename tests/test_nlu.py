import pytest

from whatsapp_attendant.knowledge import NOT_UNDERSTOOD
from whatsapp_attendant.nlu import TfidfClassifier, features, negated_words, normalize, yes_or_no
from whatsapp_attendant.providers import LocalProvider


def test_normalize_strips_accents_punctuation_and_case():
    assert normalize("Olá!!! Já PAGUEI, tá?") == "ola ja paguei ta"


def test_features_drop_stopwords_and_add_char_trigrams():
    feats = features("quero o boleto")
    assert "w:boleto" in feats and "w:quero" not in feats
    assert "c:bol" in feats


def test_ca_5_out_of_scope_and_empty_are_not_understood(kb):
    provider = LocalProvider(kb)
    assert provider.classify("receita de bolo de cenoura").intent == NOT_UNDERSTOOD
    assert provider.classify("").intent == NOT_UNDERSTOOD
    assert provider.classify("!!!").confidence == 0.0


def test_ca_5_known_intent_with_typos_is_recognized(kb):
    provider = LocalProvider(kb)
    assert provider.classify("preciso da 2 via do boleto").intent == "invoice_copy"
    assert provider.classify("qro falar com um atendnte").intent == "human_agent"


def test_ca_5_threshold_rejects_but_keeps_best_guess(kb):
    clf = TfidfClassifier(kb.labeled_examples(), threshold=0.95)
    p = clf.predict("onde está o meu pedido que comprei")
    assert p.intent == NOT_UNDERSTOOD and p.best_guess == "order_status" and not p.understood
    assert clf.predict("onde está o meu pedido que comprei", threshold=0.1).understood


def test_scores_are_sorted_and_runner_up_is_reported(kb):
    clf = TfidfClassifier(kb.labeled_examples())
    ranked = clf.scores("quero cancelar o pedido")
    assert ranked[0][0] == "cancel_order"
    assert [s for _, s in ranked] == sorted((s for _, s in ranked), reverse=True)
    assert clf.predict("quero cancelar o pedido").runner_up == ranked[1][0]


def test_classifier_needs_examples():
    with pytest.raises(ValueError):
        TfidfClassifier([])


@pytest.mark.parametrize(
    ("text", "negated"),
    [
        ("nao quero mais cancelar, pode enviar", {"cancelar"}),
        ("não preciso de atendente", {"atendente"}),
        ("não quero mais o produto, quero cancelar", {"produto"}),
        ("não quero falar com robô", {"robo"}),
        ("não quero falar com uma pessoa", {"pessoa"}),
        ("nao gostei quero cancelar", {"gostei"}),
        ("quero cancelar não", {"cancelar"}),
        ("robô não resolve, quero uma pessoa", {"resolve"}),
        ("não sei o número mas quero cancelar", {"sei"}),
        ("n quero mais cancelar", {"cancelar"}),
        ("cancela meu pedido", set()),
        ("não", set()),
    ],
)
def test_ca_14_negation_reaches_the_first_content_word_of_its_clause(text, negated):
    assert negated_words(text) == negated


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("sim", True),
        ("s", True),
        ("isso, pode cancelar", True),
        ("quero cancelar sim", True),
        ("Cancela!", True),
        ("não", False),
        ("nao quero mais cancelar, pode enviar", False),
        ("n", False),
        ("nem pensar", False),
        ("pode enviar", None),
        ("sim, não", None),
        ("talvez", None),
    ],
)
def test_ca_14_yes_or_no_reads_the_answer_to_a_confirmation(text, answer):
    assert yes_or_no(text, ("cancel", "estorn")) is answer
