# ADR-002: Local intent engine first, LLM as an optional second layer

Status: accepted
Date: 2026-10-22

## Context

Every inbound WhatsApp message needs an intent. Sending all of them to an LLM is the simplest design, but it adds cost per message, latency, a hard dependency on an external service, a privacy question (order numbers, names) and tests that need the network. Most store questions are repetitive and short.

## Decision

1. A local TF-IDF classifier over words and character trigrams decides every message first. It trains from the knowledge base in milliseconds and runs offline.
2. A message below the confidence threshold is "not understood": the bot says so, counts a failed turn and queues the message for curation.
3. Only when `ANTHROPIC_API_KEY` is set, a rejected message goes to Claude. The order number is masked first. The answer must follow a JSON schema whose `intent` is an enum of the known intents plus `none`, so a customer message cannot make the model return anything else. The answer is used only at or above `llm.min_confidence`; a refusal, a timeout or invalid JSON keeps the local result.
4. The confidence threshold is chosen on a dev split, never on the test split (ADR-004).

## Consequences

- No outbound call without a key; tests run with a fake client.
- The LLM sees only messages the local engine rejected, so it cannot fix confident wrong answers. With the dev-chosen threshold of 0.16, those are the main error (21% of simulated conversations). Routing low-margin predictions to the LLM, or asking a confirmation question, is the next experiment.
- Swapping the provider means writing one class with `classify(text) -> Prediction`.

## Alternatives considered

- LLM for every message: better language coverage, but cost and latency per message and no offline tests.
- Embeddings with a vector store: better paraphrase coverage, but a model download and a heavier stack for 9 intents.
