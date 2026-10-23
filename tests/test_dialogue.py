import threading
import time

from whatsapp_attendant.backends import ORDER_STATUSES, FakeOrderBackend
from whatsapp_attendant.config import DialogueSettings
from whatsapp_attendant.dialogue import Action, Attendant, HandoffReason
from whatsapp_attendant.knowledge import NOT_UNDERSTOOD
from whatsapp_attendant.providers import LocalProvider

PHONE = "5511000000001"


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
    status = FakeOrderBackend().lookup("654321", PHONE)["order_status"]
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


def test_ca_9_learning_queue_text_has_the_order_number_masked(attendant):
    attendant.handle(PHONE, "bicicleta voadora 123456 xyz")
    item = attendant.learning_queue[0]
    assert "123456" not in item.text and item.text == "bicicleta voadora xyz"


def test_masking_keeps_the_number_out_of_classification(attendant, kb):
    assert kb.mask_slots("o boleto venceu, pedido 731204").strip() == "o boleto venceu,"
    t = attendant.handle(PHONE, "o boleto venceu, pedido 731204")
    assert t.intent == "invoice_copy" and t.slots["order_number"] == "731204"


def test_turn_reports_latency_and_not_understood_intent(attendant):
    t = attendant.handle(PHONE, "asdfgh")
    assert t.intent == NOT_UNDERSTOOD and t.latency_ms >= 0


class _Gate:
    """Provider that blocks on messages containing "lento" until released."""

    def __init__(self, kb) -> None:
        self.local = LocalProvider(kb)
        self.entered = threading.Event()
        self.release = threading.Event()

    def classify(self, text):
        if "lento" in text:
            self.entered.set()
            self.release.wait(timeout=5)
        return self.local.classify(text)


def test_ca_16_one_slow_phone_does_not_block_another(kb):
    gate = _Gate(kb)
    attendant = Attendant(kb, gate)
    slow = threading.Thread(target=attendant.handle, args=("5511000000001", "pedido lento"))
    slow.start()
    assert gate.entered.wait(timeout=5)
    start = time.perf_counter()
    other = attendant.handle("5511000000002", "bom dia")
    elapsed = time.perf_counter() - start
    gate.release.set()
    slow.join(timeout=5)
    assert other.intent == "greeting" and elapsed < 1.0


# CA-14: negation guard and cancellation confirmation -------------------------------------------


def _confirm_text(kb, number: str) -> str:
    return kb.render(kb.intent("cancel_order").confirm, order_number=number)


def test_ca_14_a_negated_request_for_a_person_is_declined(attendant, kb):
    t = attendant.handle(PHONE, "não preciso de atendente")
    assert (t.intent, t.action, t.reply) == ("human_agent", Action.DECLINED, kb.declined_reply)
    session = attendant.session(PHONE)
    assert not session.with_human and session.failed_turns == 0


def test_ca_14_a_stored_number_is_confirmed_before_cancelling(attendant, kb):
    assert attendant.handle(PHONE, "cadê meu pedido 482915?").action is Action.ANSWER
    ask = attendant.handle(PHONE, "quero cancelar")
    assert (ask.intent, ask.action, ask.reply) == (
        "cancel_order",
        Action.CONFIRM,
        _confirm_text(kb, "482915"),
    )
    no = attendant.handle(PHONE, "nao quero mais cancelar, pode enviar")
    assert (no.action, no.reply) == (Action.DECLINED, kb.declined_reply)
    session = attendant.session(PHONE)
    assert session.pending_confirmation is None and session.pending_intent is None


def test_ca_14_yes_answers_the_cancellation(attendant, kb):
    ask = attendant.handle(PHONE, "quero cancelar o pedido 731204")
    assert (ask.action, ask.reply) == (Action.CONFIRM, _confirm_text(kb, "731204"))
    yes = attendant.handle(PHONE, "sim")
    assert (yes.intent, yes.action, yes.source) == ("cancel_order", Action.ANSWER, "confirmation")
    assert "731204" in yes.reply and "cancelamento" in yes.reply


def test_ca_14_negation_drops_a_pending_cancellation_without_a_failed_turn(attendant, kb):
    assert attendant.handle(PHONE, "quero cancelar").action is Action.ASK_SLOT
    t = attendant.handle(PHONE, "não quero mais cancelar")
    assert (t.action, t.reply) == (Action.DECLINED, kb.declined_reply)
    session = attendant.session(PHONE)
    assert session.pending_intent is None and session.failed_turns == 0


def test_ca_14_a_negated_cancellation_is_never_acted_on(attendant, kb):
    t = attendant.handle(PHONE, "nao quero cancelar meu pedido 731204")
    assert t.action is Action.DECLINED
    assert attendant.session(PHONE).pending_confirmation is None


def test_ca_14_an_unclear_answer_asks_again_and_then_hands_off(attendant, kb):
    attendant.handle(PHONE, "quero cancelar o pedido 731204")
    again = attendant.handle(PHONE, "talvez")
    assert (again.action, again.reply) == (Action.CONFIRM, _confirm_text(kb, "731204"))
    last = attendant.handle(PHONE, "hmm")
    assert last.action is Action.HANDOFF and last.handoff_reason is HandoffReason.REPEATED_FAILURES


def test_ca_14_a_confident_new_topic_leaves_the_confirmation(attendant):
    attendant.handle(PHONE, "quero cancelar o pedido 731204")
    t = attendant.handle(PHONE, "qual o horário de atendimento?")
    assert (t.intent, t.action) == ("business_hours", Action.ANSWER)
    assert attendant.session(PHONE).pending_confirmation is None


def test_ca_14_negations_of_other_words_keep_the_intent(attendant):
    assert attendant.handle(PHONE, "não quero falar com robô").action is Action.HANDOFF
    other = "5511000000002"
    t = attendant.handle(other, "nao recebi o produto quero cancelar")  # negates "recebi" only
    assert (t.intent, t.action) == ("cancel_order", Action.ASK_SLOT)


# CA-17: topic switch with a number and order ownership -----------------------------------------


def test_ca_17_a_number_for_another_order_intent_switches_topic(attendant):
    assert attendant.handle(PHONE, "cadê meu pedido?").action is Action.ASK_SLOT
    t = attendant.handle(PHONE, "quero cancelar o pedido 123456")
    assert (t.intent, t.action) == ("cancel_order", Action.CONFIRM)
    assert t.slots == {"order_number": "123456"}


def test_ca_17_a_number_reply_answers_the_pending_question(attendant):
    attendant.handle(PHONE, "cadê meu pedido?")
    t = attendant.handle(PHONE, "é o 482915")
    assert (t.intent, t.action) == ("order_status", Action.ANSWER)
    attendant.handle("5511000000003", "cadê meu pedido?")
    greeting = attendant.handle("5511000000003", "oi, o número é 654321")
    assert (greeting.intent, greeting.action) == ("order_status", Action.ANSWER)


def test_ca_17_a_number_with_a_request_for_a_person_hands_off(attendant):
    attendant.handle(PHONE, "cadê meu pedido?")
    t = attendant.handle(PHONE, "quero falar com um atendente sobre o pedido 123456")
    assert t.action is Action.HANDOFF and t.slots == {"order_number": "123456"}


def test_ca_17_an_order_of_another_phone_is_not_found(attendant, kb):
    assert attendant.handle(PHONE, "cadê meu pedido 111111?").action is Action.ANSWER
    stranger = "5511000000009"
    t = attendant.handle(stranger, "cadê meu pedido 111111?")
    slot = kb.slots["order_number"]
    assert (t.action, t.reply) == (
        Action.REASK_SLOT,
        kb.render(slot.not_found, order_number="111111"),
    )
    session = attendant.session(stranger)
    assert session.slots == {} and session.pending_intent == "order_status"
    assert session.failed_turns == 1


def test_ca_17_the_fake_backend_can_own_orders_explicitly():
    backend = FakeOrderBackend({"123456": "5511000000001"})
    assert backend.lookup("123456", "5511000000001")["order_status"] in ORDER_STATUSES
    assert backend.lookup("123456", "5511000000002") is None
    assert backend.lookup("999999", "5511000000001") is None
