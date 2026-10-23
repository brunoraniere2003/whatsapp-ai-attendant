# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
