# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `vitrine/src/build.py` takes the browser from `CHROME_PATH` or the first of `chromium`, `chrome` or `msedge` on the PATH, and stops with exit 2 when there is none; there is no machine-specific default path any more.
- Phone numbers in tests, the README and the demo and simulation generators are numbers that cannot exist (`55110…`: a Brazilian subscriber number never starts with 0). The test message id encodes the fictional `16505550123` and the demo-host test uses the documentation address `192.0.2.10`. Masked phones, `metricas.json`, the reports and the transcripts are byte-identical.

### Added

- `.env.example` lists every environment variable with an empty value; the README documents `CHROME_PATH`.

## [1.1.0] - 2026-10-23

Fixes every finding of the independent review that blocked 1.0.0 (SPEC-001 amendment A-1). Version 1.0.0 was never deployed or published, so the stricter defaults below ship as a minor version instead of a major one.

### Security

- The webhook fails closed: without `WA_APP_SECRET` every event gets 503 (`whatsapp.allow_unsigned = true` only for local tests), the service refuses to start with `WA_ACCESS_TOKEN` and no app secret, and `/health` reports `signature_check` (ADR-006).
- Bodies above `whatsapp.max_body_bytes` (1 MiB) get 413 before the HMAC, from the declared Content-Length or while streaming. A non-ASCII signature header gets 401 and JSON nested too deep gets 400 instead of 500; malformed payload parts are skipped.
- Message ids are logged only as `message_ref`, a keyed hash: a Cloud API `wamid` is the base64 of a record that holds the sender's phone.
- The verify token is compared in constant time and `hub.challenge` must be 1 to 64 digits; secrets are hidden from `repr`; `/docs`, `/redoc` and `/openapi.json` exist only in demo mode; `serve --demo` refuses a non-loopback host unless `--allow-remote-demo` is given.
- The order backend answers only about orders of the phone that asks (`OrderBackend.lookup(order_number, phone)`).

### Fixed

- "nao quero mais cancelar, pode enviar" was a cancellation and "não preciso de atendente" a handoff. A negation guard (`negation_terms` in the knowledge base, a clause rule in `nlu.negated_words`) now keeps the bot from acting on a negated cancellation or handoff.
- A cancellation needs a yes to "Confirma o cancelamento do pedido N?", also when the number was reused from an earlier question.
- A reply that carries an order number skipped the topic switch; it now switches to another order question or to a handoff and keeps the number.
- The `async` webhook ran the synchronous engine on the event loop under one process-wide lock, so a slow LLM call froze `/health` and every other customer. Messages are now handled in a worker thread with a lock per phone, and the LLM budget is 3 seconds with 1 retry (at most 5 seconds and 1 retry).
- A message id was recorded before handling, so a failure lost the message. It is now marked only after success; a failure logs the traceback, keeps the other messages of the event and answers 500 so Meta redelivers it, with a dead letter after 3 attempts.
- The leakage rule compared normalized text while the model drops stopwords and word order, so 12 test phrases and 2 dev phrases were the same model input as a training or dev phrase. Leakage is now measured on the model's representation (same word set without stopwords, or cosine of 0.95 or more, ADR-005) and those phrases were removed.
- Simulation labels: a wrong answer, a confirmed wrong cancellation included, is never resolved; `abandoned` separates "rejected, then the customer left" from `misrouted`; simulated customers answer the cancellation question and rephrase once after a miss; each conversation has its own seeded generator; an intent with a single test phrase can no longer crash the rephrase.
- Placeholders of slot questions and confirmations are validated when the knowledge base loads; slot patterns ignore case; the learning queue masks order numbers; a non-finite LLM confidence keeps the local result; texts without content words are not sent to the LLM; split values must be lists of strings; the evidence command fails when the configured threshold is not the dev choice; unexpected errors are logged with their traceback.
- The demo console used the runtime provider, so a page view could call the LLM, and it re-ran its scenarios on every request. It now uses the local engine only and runs the scenarios once.

### Changed

- Reported numbers, same seed and 300 conversations, under the stricter rules above: resolved 80.7% (242 of 300, was 72.0%), handed to a person 7.3% (was 7.0%), wrong answer or wrong flow 12.0% (was 21.0%), intent accuracy on held-out phrases 85.3% (93 of 109, was 86.8% on 121 that included the leaked phrases). Simulated customers who had asked something else said no to 38 cancellation questions; without the question each of those ended in a cancellation. With customers who never rephrase after a miss, 69.7% are resolved; `metricas.json` reports it under `sensitivity`.
- Runtime dependencies are `fastapi`, `uvicorn`, `pydantic` and `httpx` instead of `fastapi[standard]`; the LLM layer installs with `uv sync --extra llm`.
- New settings `whatsapp.allow_unsigned`, `whatsapp.max_body_bytes` and `whatsapp.max_processing_attempts`; `llm.timeout_seconds` defaults to 3 (at most 5) and `llm.max_retries` to 1 (at most 1).
- CI pins the uv version and checks the gitleaks tarball against a SHA-256 kept in the workflow.

### Added

- SPEC-001 amendment A-1 with CA-14 to CA-17, ADR-005 (leakage on the model's representation), ADR-006 (webhook processing) and the processing-errors runbook.
- Counters `oversized_bodies`, `processing_errors` and `dead_letters` in `/metrics`; actions `confirm` and `declined` in turns and transcripts.

## [1.0.0] - 2026-10-22

### Added

- WhatsApp Cloud API webhook: verification, `X-Hub-Signature-256` HMAC check, idempotency by message id, text, button and list replies, polite reply to media messages.
- Local intent engine (TF-IDF over words and character trigrams) trained from an editable, validated knowledge base of 9 intents in Brazilian Portuguese.
- Dialogue rules: order number collection with re-ask, topic switch, handoff after two failed turns or on request, silence after handoff, session TTL.
- Order number masking before classification, so the number never biases the intent or reaches an LLM.
- Optional Claude second layer for rejected messages only, constrained by a JSON schema enum, with server-side fallback; any failure keeps the local result.
- Learning queue of misunderstood messages with masked phones.
- Outbound sender for the Graph API with retries and backoff for transient errors only.
- Strict TOML configuration with a documented example equal to the defaults; secrets only from environment variables.
- JSON logs to a rotating file with masked phones, `/health`, `/metrics` and a `health` command that exits non-zero on failure.
- Seeded evidence command: threshold chosen on a dev split, accuracy on a frozen test split, 300 simulated conversations scored against the customer's real question, English and Portuguese reports.
- Opt-in demo UI: conversation console and evaluation dashboard.
- Portfolio cards, covers and screens with a reproducible generator.
- SPEC-001, ADRs 001 to 004, runbooks, SLOs, RACI, risk register and roadmap.
