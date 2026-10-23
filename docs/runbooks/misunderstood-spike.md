# Misunderstood spike

## Symptom

More customers than usual get "Não consegui identificar o assunto", or the human agents receive more conversations handed off after failures.

## Detection

The ratio `not_understood / received` in `/metrics` doubles against its weekly average, or `handoff_repeated_failures` grows faster than traffic. The learning queue grows quickly.

## Diagnosis

1. Read the newest learning queue items (console in demo, or an export in production) and group them by the best guess.
2. A new topic (a promotion, a delivery problem, a new payment method) shows up as many similar messages with no good intent.
3. A broken knowledge base edit shows up as one intent that stopped matching its usual phrases; run the evidence command and compare `test.per_intent` with the committed `metricas.json`.

## Mitigation

Add the new phrases as examples of the right intent, or add a new intent with its reply; while that is reviewed, the handoff keeps customers served by people.

## Fix

Commit the knowledge base change with the regenerated evidence; if the dev threshold moves, update `engine.confidence_threshold` (a test enforces it).

## Prevention

Review the learning queue every week and keep the off-topic examples in the dev split representative of real traffic.

## Owner

Knowledge base curator (store team), supported by the service operator.
