# Operations

How the service is run once it is connected to a real WhatsApp line. The demo in this repository runs on fictional data, so the targets below are the ones a deployment starts with, not measured history.

## Service level objectives

All indicators come from the service's own data: `/health`, `/metrics` and the JSON log.

| SLO | Indicator | Target (30 days) | Error budget |
|---|---|---|---|
| Availability | share of minutes in which `health --url` exits 0 | 99.5% | 3 h 36 min |
| Processing latency | `latency_p95_ms` from `/metrics` (engine time, before the send) | below 50 ms | 1.5 days above target |
| Delivery | `1 - send_failures / replied` | 99% | 1 failed reply in 100 |
| Understanding | `1 - not_understood / received` | 85% | 15 messages in 100 |

When a budget is spent, knowledge base and feature changes stop until the cause is fixed and recorded in the matching runbook. The understanding SLO is the business signal: the evaluation measured 86.8% on held-out phrases, so a real traffic value far below that means the knowledge base is missing a topic.

## RACI

R: responsible, A: accountable, C: consulted, I: informed.

| Activity | Developer | Service operator | Knowledge base curator (store) | Store owner |
|---|---|---|---|---|
| Code changes and releases | R, A | C | I | I |
| Deploy, secrets and monitoring | C | R, A | I | I |
| Incident response (runbooks) | C | R, A | C | I |
| Learning queue review and new examples | C | I | R | A |
| Replies, prices and policies in the knowledge base | I | I | R | A |
| Meta app, phone number and tokens | C | R | I | A |

## Risk register

| Id | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | Confident wrong answer (21% of simulated conversations) | high | medium | handoff on request, weekly learning queue review, next experiment with a confirmation question | developer |
| R2 | Restart loses sessions and processed ids, a redelivered event gets a second reply | medium | low | single replica; Redis in production (ADR-003) | operator |
| R3 | Access token expires and replies stop | medium | high | system user token, `send.failed` alert, runbook send-failures | operator |
| R4 | Forged webhook calls | medium | medium | HMAC check with the app secret, 503 without it, 413 above 1 MiB, `invalid_signatures` alert | operator |
| R5 | Personal data in logs | low | high | phones masked in logs and learning queue, message ids logged only as a keyed hash (a `wamid` encodes the phone), message text not logged | developer |
| R6 | LLM provider outage or refusal | low | low | local result kept, `llm.error` logged, the layer is optional | developer |
| R7 | Knowledge base edit breaks an intent | medium | medium | strict validation, tests, evidence regenerated in CI | curator |
| R8 | A failing dependency or bug loses customer messages | medium | high | ids marked only after success, 500 so Meta redelivers, dead letter after 3 attempts with an alert, runbook processing-errors | developer |

## Roadmap

1. Measure on real traffic: export a week of anonymized messages and rebuild the dev and test splits from them.
2. Confirmation question for predictions just above the threshold, compared with this baseline on the same seed.
3. Redis for sessions, idempotency and the learning queue, with migrations and backups.
4. Real order backend (store ERP) behind `OrderBackend`.
5. Template messages for replies outside the 24-hour window.
6. Curation screen that turns a learning queue item into a knowledge base pull request.
