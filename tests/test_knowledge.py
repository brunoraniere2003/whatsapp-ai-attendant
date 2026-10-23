import copy
import tomllib

import pytest

from whatsapp_attendant.knowledge import (
    KnowledgeBaseError,
    bundled_text,
    load_knowledge_base,
    parse_knowledge_base,
)

BASE = tomllib.loads(bundled_text("knowledge_base.toml"))


def _variant(change) -> dict:
    data = copy.deepcopy(BASE)
    change(data)
    return data


def test_bundled_knowledge_base_loads(kb):
    assert len(kb.intents) == 9 and kb.store_name == "Loja Exemplo"
    assert kb.intent("cancel_order").slot == "order_number"
    assert kb.intent("human_agent").handoff
    with pytest.raises(KeyError):
        kb.intent("missing")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["intents"].append(copy.deepcopy(d["intents"][0])), "repeated intent name"),
        (lambda d: d["intents"][0].update(examples=["oi", "olá"]), "at least 3 examples"),
        (lambda d: d["intents"][0].update(reply="Olá {cliente}"), "unknown placeholders"),
        (lambda d: d["intents"][1].update(slot="cpf"), "not defined"),
        (lambda d: d["intents"][0].update(name="not_understood"), "reserved"),
        (lambda d: d["intents"][1].update(handoff=True), "cannot both"),
        (lambda d: d["replies"].update(handoff="Até {order_number}"), "reply 'handoff'"),
        (lambda d: d["slots"]["order_number"].update(pattern="("), "invalid regular expression"),
        (lambda d: d["intents"][0].update(colour="blue"), "Extra inputs"),
        (lambda d: d["intents"][0].update(reply="Olá {"), "malformed template"),
    ],
)
def test_ca_10_inconsistent_knowledge_base_is_rejected(change, message):
    with pytest.raises(KnowledgeBaseError, match=message):
        parse_knowledge_base(_variant(change))


def test_ca_10_knowledge_base_file_errors(tmp_path):
    with pytest.raises(KnowledgeBaseError, match="not found"):
        load_knowledge_base(tmp_path / "missing.toml")
    bad = tmp_path / "kb.toml"
    bad.write_text("[store", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="not valid TOML"):
        load_knowledge_base(bad)


def test_custom_knowledge_base_file_is_used(tmp_path):
    custom = tmp_path / "kb.toml"
    custom.write_text(
        bundled_text("knowledge_base.toml").replace("Loja Exemplo", "Outra Loja"), encoding="utf-8"
    )
    assert load_knowledge_base(custom).store_name == "Outra Loja"


def test_render_fills_store_and_hours(kb):
    assert kb.render("{store} atende {hours}") == f"{kb.store_name} atende {kb.hours}"
