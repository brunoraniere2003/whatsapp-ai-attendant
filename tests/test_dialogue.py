from whatsapp_attendant.backends import ORDER_STATUSES, FakeOrderBackend
from whatsapp_attendant.config import DialogueSettings
from whatsapp_attendant.dialogue import Action, Attendant, HandoffReason
from whatsapp_attendant.knowledge import NOT_UNDERSTOOD
from whatsapp_attendant.providers import LocalProvider

PHONE = "5511999990001"


def test_ca_7_asks_for_the_order_number_reasks_and_answers(attendant, kb):
    slot = kb.slots["order_number"]
    t1 = attendant.handle(PHONE, "perdi meu boleto")
    assert (t1.intent, t1.action, t1.reply) == ("invoice_copy", Action.ASK_SLOT, slot.ask)
    t2 = attendant.handle(PHONE, "não lembro")
    assert (t2.action, t2.reply) == (Action.REASK_SLOT, slot.invalid)
    t3 = attendant.handle(PHONE, "é o pedido 123456")
    assert t3.action is Action.ANSWER and "123456" in t3.reply
    assert t3.slots == {"order_number": "123456"} and t3.source == "slot"
    assert attendant.session(PHONE).pending_intent is None


def test_ca_7_number_in_the_message_answers_at_once(attendant):
    t = attendant.handle(PHONE, "cadê meu pedido 654321?")
    assert (t.intent, t.action) == ("order_status", Action.ANSWER)
    status = FakeOrderBackend().lookup("654321")["order_status"]
    assert status in t.reply and status in ORDER_STATUSES


def test_ca_7_collected_number_is_reused_for_the_next_question(attendant):
    attendant.handle(PHONE, "meu pedido 111111 chegou?")
    t = attendant.handle(PHONE, "agora quero a nota fiscal")
    assert (t.intent, t.action) == ("invoice_copy", Action.ANSWER) and "111111" in t.reply


def test_ca_7_topic_switch_while_collecting_hands_off_on_request(attendant):
    attendant.handle(PHONE, "quero o boleto")
    t = attendant.handle(PHONE, "quero falar com atendente")
    assert (t.intent, t.action, t.handoff_reason) == (
        "human_agent",
        Action.HANDOFF,
        HandoffReason.CUSTOMER_REQUEST,
    )


def test_ca_7_switch_to_a_question_without_slot(attendant):
    attendant.handle(PHONE, "quero cancelar meu pedido")
    t = attendant.handle(PHONE, "qual o horário de atendimento?")
    assert (t.intent, t.action) == ("business_hours", Action.ANSWER)


def test_ca_8_two_misunderstandings_hand_off(attendant, kb):
    first = attendant.handle(PHONE, "xyz abc")
    assert (first.action, first.reply) == (Action.NOT_UNDERSTOOD, kb.not_understood_reply)
    second = attendant.handle(PHONE, "qwerty zzz")
    assert second.action is Action.HANDOFF
    assert second.handoff_reason is HandoffReason.REPEATED_FAILURES
    assert attendant.session(PHONE).with_human


def test_ca_8_invalid_numbers_twice_hand_off(attendant):
    attendant.handle(PHONE, "quero trocar um produto")
    attendant.handle(PHONE, "não sei")
    t = attendant.handle(PHONE, "também não sei")
    assert t.action is Action.HANDOFF and t.handoff_reason is HandoffReason.REPEATED_FAILURES


def test_ca_8_understood_message_resets_the_failure_count(attendant):
    attendant.handle(PHONE, "xyz abc")
    attendant.handle(PHONE, "bom dia")
    assert attendant.handle(PHONE, "qwerty").action is Action.NOT_UNDERSTOOD


def test_ca_8_customer_request_and_silence_after_handoff(attendant):
    t = attendant.handle(PHONE, "quero falar com uma pessoa")
    assert t.handoff_reason is HandoffReason.CUSTOMER_REQUEST
    silent = attendant.handle(PHONE, "oi?")
    assert (silent.action, silent.reply) == (Action.SILENT, None)
    assert attendant.handle_unsupported(PHONE, "image").action is Action.SILENT


def test_unsupported_media_gets_a_request_for_text(attendant, kb):
    t = attendant.handle_unsupported(PHONE, "audio")
    assert (t.action, t.reply, t.text) == (Action.UNSUPPORTED, kb.unsupported_reply, "[audio]")


def test_ca_9_learning_queue_keeps_masked_phone_and_best_guess(attendant):
    attendant.handle(PHONE, "vocês vendem bicicleta?")
    item = attendant.learning_queue[0]
    assert item.phone == "5511*******01" and item.text == "vocês vendem bicicleta?"
    assert item.best_guess and item.confidence < 0.16


def test_ca_9_idle_session_starts_over(kb, clock):
    attendant = Attendant(
        kb, LocalProvider(kb), DialogueSettings(session_ttl_seconds=60), clock=clock
    )
    attendant.handle(PHONE, "quero falar com uma pessoa")
    assert attendant.session(PHONE).with_human
    clock.advance(61)
    t = attendant.handle(PHONE, "bom dia")
    assert (t.intent, t.action) == ("greeting", Action.ANSWER)


def test_masking_keeps_the_number_out_of_classification(attendant, kb):
    assert kb.mask_slots("o boleto venceu, pedido 731204").strip() == "o boleto venceu,"
    t = attendant.handle(PHONE, "o boleto venceu, pedido 731204")
    assert t.intent == "invoice_copy" and t.slots["order_number"] == "731204"


def test_turn_reports_latency_and_not_understood_intent(attendant):
    t = attendant.handle(PHONE, "asdfgh")
    assert t.intent == NOT_UNDERSTOOD and t.latency_ms >= 0
