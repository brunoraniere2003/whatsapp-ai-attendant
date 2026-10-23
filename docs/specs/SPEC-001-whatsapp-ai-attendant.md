# SPEC-001: AI WhatsApp Attendant

Id: SPEC-001
Title: AI WhatsApp Attendant
Status: approved on 2026-10-22 (owner's standing order for portfolio pieces); amendment A-1 approved on 2026-10-23 under the same order
Owner: Bruno Raniere
Date: 2026-10-22 (A-1: 2026-10-23)
Size: M
Depends on: nothing

## 1. Objective

A WhatsApp Cloud API webhook that answers the most common questions of a fictional online store on its own, asks for the order number when it needs one, hands the conversation to a human when it cannot help or when the customer asks, and queues every misunderstood message so the knowledge base can learn from it. Why now: it is the first portfolio case of the project factory, and it must show production habits (security, idempotency, observability) and numbers measured honestly on held-out data.

## 2. Context

| Fact | Source | Consequence |
|---|---|---|
| The Cloud API verifies a webhook with `hub.mode`, `hub.verify_token` and `hub.challenge`, signs every event with `X-Hub-Signature-256` and redelivers events that were not acknowledged | Meta WhatsApp Cloud API webhook documentation | Verification, HMAC check and idempotency by message id are requirements, not extras |
| A working prototype already exists with a TF-IDF intent engine, slot collection and handoff | internal prototype of 2026-10-21 | The engine is kept and hardened; nothing starts from zero |
| The prototype counted any conversation without a handoff as resolved, even when the bot answered the wrong question | prototype simulation code | This piece counts a conversation as resolved only when the bot answered the customer's real question |
| The confidence threshold is a hyperparameter | engine design | It is chosen on a dev split; the test split is used only for the final numbers |
| The factory gate reads a fixed layout (README sections, LICENSE, CHANGELOG, specs, metrics, cards, images) | factory spec, RQ-F6 and RQ-F13 | The layout is part of the acceptance criteria |

## 3. Requirements (EARS)

### Webhook

- RQ-1: WHEN `GET /webhook` arrives with `hub.mode=subscribe` and the configured verify token, the service SHALL answer 200 with `hub.challenge` as plain text. (A-1) The token SHALL be compared in constant time, and a `hub.challenge` that is not 1 to 64 digits SHALL get 400.
- RQ-2: IF the verify token is missing or wrong, THEN the service SHALL answer 403.
- RQ-3: WHERE an app secret is configured, IF a `POST /webhook` has a missing, wrong or non-ASCII `X-Hub-Signature-256`, THEN the service SHALL answer 401 and process nothing. (A-1) IF no app secret is configured, THEN `POST /webhook` SHALL answer 503 and process nothing, unless `whatsapp.allow_unsigned` is true (local tests only, default false). The service SHALL refuse to start with a configuration error when `WA_ACCESS_TOKEN` is set without `WA_APP_SECRET`, and `/health` SHALL report a `signature_check`.
- RQ-4: WHEN a `POST /webhook` carries a text message, the service SHALL answer it through the dialogue engine and send the reply after the HTTP response is returned.
- RQ-5: IF a message id was already processed, or is being processed, inside the idempotency window, THEN the service SHALL skip it and count it as a duplicate. (A-1) A message id SHALL be marked processed only after it was handled. IF handling a message raises, THEN the service SHALL log `message.failed` with the traceback, still handle the other messages of the payload, and answer 500 so Meta redelivers the event; after `whatsapp.max_processing_attempts` failed attempts the message SHALL be dead-lettered (marked, counted and logged) and the event answered 200.
- RQ-6: WHEN a message is not text (image, audio, sticker and similar), the service SHALL reply with the knowledge base message for unsupported types.
- RQ-7: IF the body is not valid JSON, THEN the service SHALL answer 400; events without messages (delivery statuses) SHALL be acknowledged with 200 and no reply. (A-1) JSON nested too deep to parse SHALL get 400, and malformed parts of a valid payload (an entry, change or message that is not an object, a phone, id or text body that is not a string) SHALL be skipped, never answered with 500.
- RQ-33 (A-1): IF the body is larger than `whatsapp.max_body_bytes` (1 MiB by default), by its declared Content-Length or by the bytes actually received, THEN the service SHALL answer 413 before checking the signature and SHALL read no more than the limit.
- RQ-34 (A-1): The webhook SHALL handle messages outside the event loop, and the attendant SHALL serialize the messages of one phone only, so a slow classification never delays `/health`, `/metrics` or another phone. The LLM call SHALL time out in at most 5 seconds (3 by default) with at most 1 retry (1 by default).

### Intent engine

- RQ-8: The local classifier SHALL learn only from the knowledge base examples and SHALL return "not understood" when the best similarity is below the configured confidence threshold.
- RQ-9: WHERE an LLM API key is set in the environment, WHEN the local classifier returns "not understood", the service SHALL ask the LLM to choose one of the knowledge base intents and SHALL accept the answer only if it is a known intent with at least the configured minimum confidence.
- RQ-10: IF the LLM call fails, times out, is refused or returns a confidence that is not a finite number, THEN the service SHALL keep the local result and log `llm.error`. (A-1) A message with no word left after masking and stopword removal SHALL not be sent to the LLM.
- RQ-11: WHILE no LLM key is set, the service SHALL make no outbound call to classify a message.

### Dialogue

- RQ-12: WHEN an intent that needs the order number is recognized and the message has no valid order number, the attendant SHALL ask for it and keep the intent pending; WHEN the number is already in the message, it SHALL answer at once.
- RQ-13: WHILE an order number is pending, WHEN the next message has no valid number, the attendant SHALL switch topic if the message is another intent with confidence at or above the switch threshold, and otherwise SHALL ask again and count a failed turn. (A-1) WHEN the next message carries a valid number, the attendant SHALL classify the masked text first; IF it is a different intent at or above the switch threshold that collects the same number or hands off, THEN it SHALL keep the number and switch to that intent; otherwise the number answers the pending intent.
- RQ-14: WHEN the number of consecutive failed turns (not understood or invalid order number) reaches the configured maximum, the attendant SHALL hand the conversation to a human with reason `repeated_failures`.
- RQ-15: WHEN the customer asks for a person, the attendant SHALL hand off at once with reason `customer_request`.
- RQ-16: WHILE a conversation is with a human, the attendant SHALL not reply.
- RQ-17: WHEN a message is not understood, the attendant SHALL add it to the learning queue with the phone masked, the best guess and its confidence. (A-1) The queued text SHALL have its order numbers masked.
- RQ-18: WHEN a session has been idle for longer than the session TTL, the attendant SHALL start a new session for that phone.
- RQ-35 (A-1): IF the customer negates the key word of a guarded intent (the intent's `negation_terms`; cancellation and every handoff intent are guarded), as in "não quero mais cancelar" or "não preciso de atendente", THEN the attendant SHALL not act on that intent, SHALL drop it when it was the pending question, SHALL reply with `replies.declined` and SHALL not count a failed turn.
- RQ-36 (A-1): WHEN an intent with a `confirm` question (cancellation) has its order number, including a number reused from an earlier question, the attendant SHALL ask that yes or no question before answering. A yes ("sim", "pode cancelar") answers the intent; a no ("não", "não quero mais cancelar") declines it; a confident different intent switches topic; anything else asks again and counts a failed turn.
- RQ-37 (A-1): The order backend SHALL receive the order number and the customer's phone. IF it returns nothing (unknown order, or an order of another phone), THEN the attendant SHALL forget that number, ask for it again with the slot's `not_found` reply and count a failed turn.

### Configuration and knowledge base

- RQ-19: The service SHALL load its settings from a TOML file validated strictly; IF a key is unknown or a value is out of range, THEN it SHALL stop with an error that names the key.
- RQ-20: The service SHALL load the knowledge base from TOML and SHALL reject it when intent names repeat, an intent has fewer than 3 examples, a reply uses an unknown placeholder or a slot is undefined. (A-1) It SHALL also reject an unknown placeholder in a slot question (`ask`, `invalid`, `not_found`) or a `confirm` question, a handoff or confirmable intent without `negation_terms`, and a slot served by the order backend without a `not_found` reply. Slot patterns SHALL match regardless of case.
- RQ-21: Secrets (verify token, access token, app secret, LLM key) SHALL come only from environment variables. (A-1) They SHALL not appear in the `repr` of the secrets object.

### Observability and outbound delivery

- RQ-22: The service SHALL write structured JSON logs to a rotating file, never to stdout, with phone numbers masked. (A-1) Message ids (a Cloud API `wamid` is the base64 of a record that holds the sender's phone) SHALL be logged only as `message_ref`, a keyed hash with a key drawn at startup, and unexpected errors SHALL be logged with their traceback.
- RQ-23: `GET /health` SHALL answer 200 when the knowledge base loads and the classifier self-test passes, and 503 otherwise; `python -m whatsapp_attendant health` SHALL exit 0 or 1 accordingly. (A-1) `/health` SHALL also fail when the webhook would refuse every event (no app secret and unsigned events not allowed).
- RQ-24: `GET /metrics` SHALL return the instance counters (received, replied, duplicates, handoffs by reason, not understood, learning queue size, send failures) and the p50 and p95 processing latency.
- RQ-25: WHEN a Cloud API send fails with 429, a 5xx or a network error, the sender SHALL retry with exponential backoff up to the configured attempts; IF it fails with any other 4xx, THEN it SHALL not retry and SHALL log `send.failed`.

### Evaluation and evidence

- RQ-26: The evidence command SHALL report intent accuracy only on the test split, which SHALL share no normalized phrase with the training examples or the dev split. (A-1) Overlap is measured in the representation the model uses: no two phrases may have the same set of words after stopword removal (order and repetition ignored), and no pair may reach a TF-IDF cosine of 0.95. The dev split is checked against training, the test split against training and dev, and every split value SHALL be a list of strings.
- RQ-27: The configured confidence threshold SHALL equal the threshold selected on the dev split by the threshold sweep. (A-1) The evidence command SHALL fail when they differ.
- RQ-28: WHEN `python -m whatsapp_attendant evidence` runs twice with the same seed, `evidencia/metricas.json` SHALL be byte-identical.
- RQ-29: The simulation SHALL count a conversation as resolved only when the bot answered the customer's real main question without a handoff. (A-1) A conversation with a wrong substantive answer (an answer to an intent the customer did not mean, a confirmed wrong cancellation included) is never resolved: it is `misrouted`, as is one where the bot started a wrong flow and never answered. A conversation where the bot gave no wrong answer but the customer left without one is `abandoned`. A simulated customer rephrases once when the bot rejects the main question or asks for an order number they do not have, says yes to a confirmation of their real question and no to any other.

### Demo UI and portfolio

- RQ-30: WHERE the demo UI is enabled, the service SHALL serve `/console` (scripted conversations run live through the engine, plus a message box) and `/dashboard` (the evaluation report); WHILE it is disabled, both SHALL answer 404. (A-1) The console SHALL use only the local engine, never the LLM; the scripted scenarios SHALL run once per process; `serve --demo` SHALL refuse a host that is not a loopback address unless `--allow-remote-demo` is given; `/docs`, `/redoc` and `/openapi.json` SHALL exist only in demo mode.
- RQ-31: The portfolio cards SHALL use only numbers present in `evidencia/metricas.json` and SHALL contain no dashes, emoji, markdown, links or contact data, and at most one exclamation mark.
- RQ-32: The covers and the screens SHALL be PNG files of exactly 1600x900.

## 4. Acceptance criteria

### CA-1: webhook verification (covers RQ-1, RQ-2)

- Given the service with verify token `secret`
- When `GET /webhook?hub.mode=subscribe&hub.verify_token=secret&hub.challenge=42` arrives
- Then the answer is 200 with body `42`
- And with a wrong token the answer is 403

### CA-2: signed events (covers RQ-3)

- Given an app secret configured
- When an event arrives with a correct signature, with a wrong one and with none
- Then the first is processed (200) and the other two get 401 and send nothing

### CA-3: reply and idempotency (covers RQ-4, RQ-5)

- Given a text message "bom dia" with id `wamid.1`
- When it is posted twice
- Then exactly one greeting reply is sent and `/metrics` shows 1 received and 1 duplicate

### CA-4: non-text and status events (covers RQ-6, RQ-7)

- Given an image message, a delivery status event and a body that is not JSON
- When they are posted
- Then the image gets the unsupported-type reply, the status gets 200 and nothing is sent, and the invalid body gets 400

### CA-5: threshold and out of scope (covers RQ-8)

- Given the bundled knowledge base
- When "receita de bolo de cenoura" and an empty message are classified
- Then both are "not understood", and "preciso da 2 via do boleto" is `invoice_copy`

### CA-6: optional LLM layer (covers RQ-9, RQ-10, RQ-11)

- Given no LLM key, the provider is local only and no client is built
- Given a fake LLM client, a low-confidence message is resolved by the LLM when it answers a known intent above the minimum confidence
- And an unknown intent, a low confidence, a refusal or an exception keep the local result and log `llm.error` for the failures

### CA-7: order number (covers RQ-12, RQ-13)

- Given "perdi meu boleto", the bot asks for the order number; "não lembro" makes it ask again; "é o pedido 123456" gets the answer with the number
- Given "cadê meu pedido 654321?", the bot answers at once
- Given a pending order number, "quero falar com atendente" switches topic and hands off

### CA-8: handoff (covers RQ-14, RQ-15, RQ-16)

- Given two consecutive messages that are not understood, the second hands off with reason `repeated_failures`
- Given "quero falar com uma pessoa", the bot hands off with reason `customer_request`
- And after a handoff the bot sends no reply

### CA-9: learning queue and session TTL (covers RQ-17, RQ-18)

- Given a message that is not understood, the learning queue gets one item with the phone masked, the order number masked and the best guess
- Given a session idle for longer than the TTL, the next message starts a new session

### CA-10: configuration and knowledge base (covers RQ-19, RQ-20, RQ-21)

- Given `config.example.toml`, it loads and equals the built-in defaults
- Given a config with an unknown key or a threshold of 2.0, loading fails and the error names the key
- Given a knowledge base with a repeated intent, too few examples, an unknown placeholder (in a reply, a slot question or a confirmation) or an undefined slot, loading fails
- And no secret field exists in the settings model, and the secrets never show in a `repr`

### CA-11: observability and delivery (covers RQ-22, RQ-23, RQ-24, RQ-25)

- Given a processed message, the log file has JSON lines with `message.received` and a masked phone, and stdout has nothing
- Given a healthy service, `/health` is 200 and the CLI exits 0; with a broken knowledge base it exits 1
- Given a send that fails with 503 twice and then succeeds, it is retried and delivered; given a 401, it is attempted once and logged as `send.failed`

### CA-12: honest, reproducible evidence (covers RQ-26, RQ-27, RQ-28, RQ-29)

- Given the training examples, the dev split and the test split, no two of them hold the same words after stopword removal, in any order, or a pair with cosine 0.95 or more
- Given the dev split, the sweep selects the threshold that is in the default configuration
- Given two runs of the evidence command with seed 42, the metrics files are identical and equal to the committed `evidencia/metricas.json`
- Given a simulated conversation where the bot answers a different question, it is counted as misrouted, not resolved, even when it also answered the right one later
- Given a conversation where the bot only rejected and the customer left, it is counted as abandoned
- Given a configured threshold that is not the dev choice, the evidence command fails

### CA-13: demo UI and portfolio (covers RQ-30, RQ-31, RQ-32)

- Given the demo UI enabled, `/console` and `/dashboard` answer 200; disabled, they answer 404, as do `/docs` and `/openapi.json`
- Given an LLM provider in the runtime, the console never calls it, and the scenarios run once
- Given `serve --demo --host 0.0.0.0` without `--allow-remote-demo`, the command exits 2
- Given the cards, every number in them is in `evidencia/metricas.json` and the style rules pass
- Given the 4 PNG files under `vitrine/`, each one is 1600x900

### CA-14: negation guard and cancellation confirmation (covers RQ-35, RQ-36)

- Given "não preciso de atendente", the bot does not hand off and answers with the declined reply
- Given "cadê meu pedido 482915?" and then "quero cancelar", the bot asks "Confirma o cancelamento do pedido 482915?" instead of cancelling
- And "nao quero mais cancelar, pode enviar" declines: the order is not cancelled
- Given "quero cancelar o pedido 731204" and then "sim", the cancellation is answered
- Given a pending cancellation without a number, "não quero mais cancelar" drops the pending question without a failed turn

### CA-15: webhook hardening (covers RQ-1, RQ-3, RQ-7, RQ-22, RQ-33)

- Given no app secret, `POST /webhook` answers 503 and `/health` reports `signature_check` false; with `allow_unsigned` it answers 200
- Given an access token without an app secret, the app refuses to start
- Given a non-ASCII signature header, the answer is 401; given a body above the limit, declared or streamed, the answer is 413
- Given malformed parts in a payload or JSON nested too deep, the service answers 200 or 400, never 500
- Given a realistic `wamid` that encodes 16505076520, neither the id nor the number appears in the log
- Given a `hub.challenge` that is not digits, verification answers 400

### CA-16: non-blocking handling and idempotency after success (covers RQ-5, RQ-34)

- Given a provider that blocks while classifying, `/metrics` answers before the webhook returns
- Given a message whose handling raises, the other message of the payload is answered, the event gets 500 and the message is not marked; the redelivery is handled
- Given a message that fails `max_processing_attempts` times, it is dead-lettered and the event gets 200
- Given the defaults, the LLM call has a 3 second timeout and 1 retry, and a timeout above 5 seconds or 2 retries is a configuration error

### CA-17: topic switch with a number and order ownership (covers RQ-13, RQ-37)

- Given a pending order status, "quero cancelar o pedido 123456" switches to the cancellation with that number
- Given a pending order status, "é o 482915" answers the order status
- Given an order looked up by one phone, another phone asking about it gets the `not_found` reply and a failed turn

## 5. Events and data

| Id | Event or data | When | Fields | Consumer |
|---|---|---|---|---|
| EV-1 | `message.received` | every new inbound message | phone (masked), message_ref, kind | operator |
| EV-2 | `message.replied` | every reply produced | phone (masked), intent, confidence, action, latency_ms | operator |
| EV-3 | `handoff` | conversation handed to a human | phone (masked), reason | human agents |
| EV-4 | `message.duplicate`, `signature.invalid`, `signature.unconfigured`, `body.too_large` | idempotency hit, bad or missing signature setup, oversized body | message_ref or none | operator |
| EV-7 | `message.failed` | handling a message raised | phone (masked), message_ref, dead_letter, traceback | operator |
| EV-8 | `declined`, `confirmation.asked` | negated guarded intent, yes or no question | phone (masked), intent | operator |
| EV-5 | `send.retry`, `send.failed` | outbound delivery problems | status, attempt | operator |
| EV-6 | `llm.used`, `llm.error` | LLM layer activity | intent, confidence or error | operator |
| D-1 | `src/whatsapp_attendant/data/knowledge_base.toml` | versioned | intents, examples, replies, slots | classifier and attendant |
| D-2 | `src/whatsapp_attendant/data/eval/dev.toml` and `test.toml` | versioned | phrases per intent and out of scope | evaluation |
| D-3 | `evidencia/metricas.json` | evidence command | see `evidence.py` | README, cards, factory gate |

## 6. Out of scope

- Real ERP or payment integration: the order lookup is a deterministic fake behind an interface, because there is no real store.
- Persistent sessions and a shared idempotency store: state is in memory (ADR-003); a production deployment with several replicas needs Redis or a database.
- A curation UI for the learning queue: the queue is exposed in the console and in the metrics; approving examples is an edit of the knowledge base file.
- Media understanding (audio transcription, images): out of the demo; unsupported types get a polite reply.
- Languages other than Brazilian Portuguese in the bundled knowledge base: the engine is language agnostic, but every language needs its own examples and evaluation.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Numbers that look better than reality | threshold chosen on dev, test split frozen, misrouted answers are not counted as resolved |
| Prompt injection through the LLM layer | the LLM output is constrained to a JSON schema whose intent is an enum of known intents |
| Meta redelivers events | idempotency by message id with a TTL |
| Forged webhook calls | HMAC signature check; without an app secret the webhook answers 503 (A-1) |
| "Não quero cancelar" taken as a cancellation | negation guard and a yes or no confirmation before cancelling (A-1) |
| Near-duplicate test phrases inflate accuracy | leakage measured on the model's own representation (A-1, ADR-005) |
| A flood of failures on outbound sends | retries only on transient errors, bounded attempts, `send.failed` counter for alerting |

## 8. Decisions

| Id | Decision | Reason | ADR |
|---|---|---|---|
| D-1 | Python 3.13, FastAPI, uv, ruff, pytest | template stack | ADR-001 |
| D-2 | Local TF-IDF engine first, LLM only as an optional second layer | cost, latency and offline tests | ADR-002 |
| D-3 | In-memory state behind small interfaces | demo scope; swap for Redis in production | ADR-003 |
| D-4 | Negation found by a rule over clauses (a cue word negates the first content word after it, light words skipped), not by the classifier | a bag-of-words model cannot see negation; the rule is local, testable and explainable | this spec, A-1 |
| D-5 | Leakage measured on the stopword-free word set and the TF-IDF cosine of the model | the normalized-text rule let 12 test phrases equal to training or dev through | ADR-005 |
| D-6 | The webhook handles messages in a worker thread before answering, marks ids after success and answers 500 on failure | Meta's redelivery then retries a failed message, bounded by a dead letter | ADR-006 |

## 9. Open questions

None. The piece runs on fictional data and the owner's standing order approves the spec.

## 10. Traceability

| CA | Requirements | Tests | Status |
|---|---|---|---|
| CA-1 | RQ-1, RQ-2 | `tests/test_api.py::test_ca_1_*` | passing |
| CA-2 | RQ-3 | `tests/test_api.py::test_ca_2_*` | passing |
| CA-3 | RQ-4, RQ-5 | `tests/test_api.py::test_ca_3_*` | passing |
| CA-4 | RQ-6, RQ-7 | `tests/test_api.py::test_ca_4_*` | passing |
| CA-5 | RQ-8 | `tests/test_nlu.py::test_ca_5_*` | passing |
| CA-6 | RQ-9, RQ-10, RQ-11 | `tests/test_providers.py::test_ca_6_*` | passing |
| CA-7 | RQ-12, RQ-13 | `tests/test_dialogue.py::test_ca_7_*` | passing |
| CA-8 | RQ-14, RQ-15, RQ-16 | `tests/test_dialogue.py::test_ca_8_*` | passing |
| CA-9 | RQ-17, RQ-18 | `tests/test_dialogue.py::test_ca_9_*` | passing |
| CA-10 | RQ-19, RQ-20, RQ-21 | `tests/test_config.py::test_ca_10_*`, `tests/test_knowledge.py::test_ca_10_*` | passing |
| CA-11 | RQ-22 to RQ-25 | `tests/test_api.py::test_ca_11_*`, `tests/test_whatsapp.py::test_ca_11_*`, `tests/test_cli.py::test_ca_11_*` | passing |
| CA-12 | RQ-26 to RQ-29 | `tests/test_evaluation.py::test_ca_12_*`, `tests/test_evidence.py::test_ca_12_*` | passing |
| CA-13 | RQ-30, RQ-31, RQ-32 | `tests/test_api.py::test_ca_13_*`, `tests/test_cli.py::test_ca_13_*`, `tests/test_vitrine.py::test_ca_13_*` | passing |
| CA-14 | RQ-35, RQ-36 | `tests/test_dialogue.py::test_ca_14_*`, `tests/test_nlu.py::test_ca_14_*` | passing |
| CA-15 | RQ-1, RQ-3, RQ-7, RQ-22, RQ-33 | `tests/test_api.py::test_ca_15_*`, `tests/test_whatsapp.py::test_ca_15_*` | passing |
| CA-16 | RQ-5, RQ-34 | `tests/test_api.py::test_ca_16_*`, `tests/test_providers.py::test_ca_16_*`, `tests/test_config.py::test_ca_16_*` | passing |
| CA-17 | RQ-13, RQ-37 | `tests/test_dialogue.py::test_ca_17_*` | passing |

## 11. Amendments

### A-1 (2026-10-23): findings of the independent review of piece 1

The review blocked the first version. Every finding became a requirement change, an acceptance criterion and a regression test written before the fix.

| Finding | Changed | New |
|---|---|---|
| "não quero mais cancelar, pode enviar" became a cancellation, and a stored number was reused without asking | RQ-13 | RQ-35, RQ-36, CA-14 |
| The leakage rule compared normalized text while the model drops stopwords, so 12 test phrases equal to training or dev went through | RQ-26, RQ-27, CA-12 | ADR-005 |
| The `async` webhook ran the synchronous engine on the event loop, under one global lock, with a 10 s LLM budget | RQ-10 | RQ-34, CA-16 |
| Without an app secret, unsigned events were accepted | RQ-3, RQ-23 | CA-15 |
| Message ids, which encode the sender's phone, were logged | RQ-22 | CA-15 |
| The body was read whole, with no limit, before the signature check | RQ-7 | RQ-33, CA-15 |
| A message id was recorded before processing, so a failure lost the message | RQ-5 | CA-16, ADR-006 |
| Rejected-then-abandoned conversations were labelled misrouted, and a wrong cancellation could count as resolved | RQ-29, CA-12 | |
| A number in the reply skipped the topic switch | RQ-13 | CA-17 |
| Placeholders of slot questions were not validated, and slot patterns were case sensitive | RQ-20, CA-10 | |
| Malformed payload parts and a non-ASCII signature raised 500 | RQ-3, RQ-7 | CA-15 |
| The order lookup ignored who was asking | | RQ-37, CA-17 |
| The demo console could call the LLM on every page view, re-ran the scenarios per request and could be served on any interface | RQ-30, CA-13 | |
| Smaller ones: constant-time verify token, challenge format, secrets in `repr`, API docs outside demo mode, non-finite LLM confidence, unmasked learning queue text, split values not checked as lists of strings | RQ-1, RQ-10, RQ-17, RQ-21, RQ-26, RQ-30 | |
