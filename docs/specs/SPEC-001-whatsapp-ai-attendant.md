# SPEC-001: AI WhatsApp Attendant

Id: SPEC-001
Title: AI WhatsApp Attendant
Status: approved on 2026-10-22 (owner's standing order for portfolio pieces)
Owner: Bruno Raniere
Date: 2026-10-22
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

- RQ-1: WHEN `GET /webhook` arrives with `hub.mode=subscribe` and the configured verify token, the service SHALL answer 200 with `hub.challenge` as plain text.
- RQ-2: IF the verify token is missing or wrong, THEN the service SHALL answer 403.
- RQ-3: WHERE an app secret is configured, IF a `POST /webhook` has a missing or wrong `X-Hub-Signature-256`, THEN the service SHALL answer 401 and process nothing.
- RQ-4: WHEN a `POST /webhook` carries a text message, the service SHALL answer it through the dialogue engine and send the reply after the HTTP response is returned.
- RQ-5: IF a message id was already processed inside the idempotency window, THEN the service SHALL skip it and count it as a duplicate.
- RQ-6: WHEN a message is not text (image, audio, sticker and similar), the service SHALL reply with the knowledge base message for unsupported types.
- RQ-7: IF the body is not valid JSON, THEN the service SHALL answer 400; events without messages (delivery statuses) SHALL be acknowledged with 200 and no reply.

### Intent engine

- RQ-8: The local classifier SHALL learn only from the knowledge base examples and SHALL return "not understood" when the best similarity is below the configured confidence threshold.
- RQ-9: WHERE an LLM API key is set in the environment, WHEN the local classifier returns "not understood", the service SHALL ask the LLM to choose one of the knowledge base intents and SHALL accept the answer only if it is a known intent with at least the configured minimum confidence.
- RQ-10: IF the LLM call fails, times out or is refused, THEN the service SHALL keep the local result and log `llm.error`.
- RQ-11: WHILE no LLM key is set, the service SHALL make no outbound call to classify a message.

### Dialogue

- RQ-12: WHEN an intent that needs the order number is recognized and the message has no valid order number, the attendant SHALL ask for it and keep the intent pending; WHEN the number is already in the message, it SHALL answer at once.
- RQ-13: WHILE an order number is pending, WHEN the next message has no valid number, the attendant SHALL switch topic if the message is another intent with confidence at or above the switch threshold, and otherwise SHALL ask again and count a failed turn.
- RQ-14: WHEN the number of consecutive failed turns (not understood or invalid order number) reaches the configured maximum, the attendant SHALL hand the conversation to a human with reason `repeated_failures`.
- RQ-15: WHEN the customer asks for a person, the attendant SHALL hand off at once with reason `customer_request`.
- RQ-16: WHILE a conversation is with a human, the attendant SHALL not reply.
- RQ-17: WHEN a message is not understood, the attendant SHALL add it to the learning queue with the phone masked, the best guess and its confidence.
- RQ-18: WHEN a session has been idle for longer than the session TTL, the attendant SHALL start a new session for that phone.

### Configuration and knowledge base

- RQ-19: The service SHALL load its settings from a TOML file validated strictly; IF a key is unknown or a value is out of range, THEN it SHALL stop with an error that names the key.
- RQ-20: The service SHALL load the knowledge base from TOML and SHALL reject it when intent names repeat, an intent has fewer than 3 examples, a reply uses an unknown placeholder or a slot is undefined.
- RQ-21: Secrets (verify token, access token, app secret, LLM key) SHALL come only from environment variables.

### Observability and outbound delivery

- RQ-22: The service SHALL write structured JSON logs to a rotating file, never to stdout, with phone numbers masked.
- RQ-23: `GET /health` SHALL answer 200 when the knowledge base loads and the classifier self-test passes, and 503 otherwise; `python -m whatsapp_attendant health` SHALL exit 0 or 1 accordingly.
- RQ-24: `GET /metrics` SHALL return the instance counters (received, replied, duplicates, handoffs by reason, not understood, learning queue size, send failures) and the p50 and p95 processing latency.
- RQ-25: WHEN a Cloud API send fails with 429, a 5xx or a network error, the sender SHALL retry with exponential backoff up to the configured attempts; IF it fails with any other 4xx, THEN it SHALL not retry and SHALL log `send.failed`.

### Evaluation and evidence

- RQ-26: The evidence command SHALL report intent accuracy only on the test split, which SHALL share no normalized phrase with the training examples or the dev split.
- RQ-27: The configured confidence threshold SHALL equal the threshold selected on the dev split by the threshold sweep.
- RQ-28: WHEN `python -m whatsapp_attendant evidence` runs twice with the same seed, `evidencia/metricas.json` SHALL be byte-identical.
- RQ-29: The simulation SHALL count a conversation as resolved only when the bot answered the customer's real main question without a handoff.

### Demo UI and portfolio

- RQ-30: WHERE the demo UI is enabled, the service SHALL serve `/console` (scripted conversations run live through the engine, plus a message box) and `/dashboard` (the evaluation report); WHILE it is disabled, both SHALL answer 404.
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

- Given a message that is not understood, the learning queue gets one item with the phone masked and the best guess
- Given a session idle for longer than the TTL, the next message starts a new session

### CA-10: configuration and knowledge base (covers RQ-19, RQ-20, RQ-21)

- Given `config.example.toml`, it loads and equals the built-in defaults
- Given a config with an unknown key or a threshold of 2.0, loading fails and the error names the key
- Given a knowledge base with a repeated intent, too few examples, an unknown placeholder or an undefined slot, loading fails
- And no secret field exists in the settings model

### CA-11: observability and delivery (covers RQ-22, RQ-23, RQ-24, RQ-25)

- Given a processed message, the log file has JSON lines with `message.received` and a masked phone, and stdout has nothing
- Given a healthy service, `/health` is 200 and the CLI exits 0; with a broken knowledge base it exits 1
- Given a send that fails with 503 twice and then succeeds, it is retried and delivered; given a 401, it is attempted once and logged as `send.failed`

### CA-12: honest, reproducible evidence (covers RQ-26, RQ-27, RQ-28, RQ-29)

- Given the training examples, the dev split and the test split, no normalized phrase appears in two of them
- Given the dev split, the sweep selects the threshold that is in the default configuration
- Given two runs of the evidence command with seed 42, the metrics files are identical and equal to the committed `evidencia/metricas.json`
- Given a simulated conversation where the bot answers a different question, it is counted as misrouted, not resolved

### CA-13: demo UI and portfolio (covers RQ-30, RQ-31, RQ-32)

- Given the demo UI enabled, `/console` and `/dashboard` answer 200; disabled, they answer 404
- Given the cards, every number in them is in `evidencia/metricas.json` and the style rules pass
- Given the 4 PNG files under `vitrine/`, each one is 1600x900

## 5. Events and data

| Id | Event or data | When | Fields | Consumer |
|---|---|---|---|---|
| EV-1 | `message.received` | every new inbound message | phone (masked), message_id, kind | operator |
| EV-2 | `message.replied` | every reply produced | phone (masked), intent, confidence, action, latency_ms | operator |
| EV-3 | `handoff` | conversation handed to a human | phone (masked), reason | human agents |
| EV-4 | `message.duplicate`, `signature.invalid` | idempotency hit, bad signature | message_id or none | operator |
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
| Forged webhook calls | HMAC signature check when the app secret is configured |
| A flood of failures on outbound sends | retries only on transient errors, bounded attempts, `send.failed` counter for alerting |

## 8. Decisions

| Id | Decision | Reason | ADR |
|---|---|---|---|
| D-1 | Python 3.13, FastAPI, uv, ruff, pytest | template stack | ADR-001 |
| D-2 | Local TF-IDF engine first, LLM only as an optional second layer | cost, latency and offline tests | ADR-002 |
| D-3 | In-memory state behind small interfaces | demo scope; swap for Redis in production | ADR-003 |

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
| CA-13 | RQ-30, RQ-31, RQ-32 | `tests/test_api.py::test_ca_13_*`, `tests/test_vitrine.py::test_ca_13_*` | passing |

## 11. Amendments

None yet.
