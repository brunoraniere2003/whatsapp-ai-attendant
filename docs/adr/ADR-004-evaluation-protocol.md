# ADR-004: Evaluation protocol

Status: accepted
Date: 2026-10-22

## Context

A portfolio number that looks too good is worse than no number. The earlier prototype counted any conversation without a handoff as resolved, even when the bot answered the wrong question, and it chose its threshold without a separate split.

## Decision

- Three disjoint sets: training examples (the knowledge base), a dev split (73 phrases) and a test split (137 phrases). A test fails if any normalized phrase appears in two of them.
- The test split was written and committed before any evaluation code existed. It changed only once, when the leakage rule removed 5 phrases that repeated training examples.
- The dev split chooses the confidence threshold: overall accuracy (each phrase counts once, off-topic phrases included, about 14% of the split) over a grid from 0.10 to 0.60, taking the median of the best thresholds. A test keeps the configured default equal to that choice.
- Edits to the knowledge base were guided by dev errors only. The masking of the order number was decided by running the simulation on the dev split.
- Reported numbers come from the test split. The simulation draws customer messages from the test split, adds typos, filler words and order numbers with a fixed seed, and scores each conversation against the customer's real main question: resolved, handed off (on request, after failures, or without a request) or misrouted.
- `evidencia/metricas.json` has no timings and no dates, so the same seed gives the same bytes; a test compares it with a fresh run.

## Consequences

- The headline is lower than a naive count would give (72.0% resolved instead of the 93.0% of conversations without a handoff), and the README explains why.
- Changing the knowledge base requires regenerating the evidence and, if the dev choice moves, the default threshold.
