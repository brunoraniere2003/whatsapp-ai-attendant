# ADR-004: Evaluation protocol

Status: accepted; the leakage rule is amended by ADR-005 (2026-10-23)
Date: 2026-10-22

## Context

A portfolio number that looks too good is worse than no number. The earlier prototype counted any conversation without a handoff as resolved, even when the bot answered the wrong question, and it chose its threshold without a separate split.

## Decision

- Three disjoint sets: training examples (the knowledge base), a dev split and a test split. A test fails if any phrase of one set is the same model input as a phrase of another (ADR-005; the first version compared normalized text only). After the ADR-005 cleanup the dev split has 71 phrases and the test split 125.
- The test split was written and committed before any evaluation code existed. It has only lost phrases: 5 that repeated training examples word for word, then 12 that were the same model input as a training or dev phrase (ADR-005). None was added or reworded.
- The dev split chooses the confidence threshold: overall accuracy (each phrase counts once, off-topic phrases included, about 14% of the split) over a grid from 0.10 to 0.60, taking the median of the best thresholds. A test keeps the configured default equal to that choice.
- Edits to the knowledge base were guided by dev errors only. The masking of the order number was decided by running the simulation on the dev split.
- Reported numbers come from the test split. The simulation draws customer messages from the test split, adds typos, filler words and order numbers with a fixed seed (one generator per conversation), and scores each conversation against what the customer meant by every message: resolved (main question answered, no wrong answer on the way), handed off (on request, after failures, or without a request), misrouted (a wrong answer or a wrong flow) or abandoned (rejected, never answered wrong). A sensitivity run with customers who never rephrase is reported next to it.
- `evidencia/metricas.json` has no timings and no dates, so the same seed gives the same bytes; a test compares it with a fresh run.

## Consequences

- The headline is lower than a naive count would give (80.7% resolved instead of the 92.7% of conversations without a handoff), and the README explains why.
- Changing the knowledge base requires regenerating the evidence and, if the dev choice moves, the default threshold.
