# ADR-005: Leakage measured on the model's own representation

Status: accepted (amends ADR-004)
Date: 2026-10-23

## Context

ADR-004 kept the training examples, the dev split and the test split disjoint by comparing normalized text (lowercase, no accents, no punctuation). The classifier does not see normalized text: it drops stopwords such as "quero", "o", "meu" and "por favor" and counts words, so order and repetition do not matter. The independent review of piece 1 found that 12 of the 121 in-scope test phrases were, for the model, the same input as a training or dev phrase, with cosine 1.0:

| Test phrase | Same input as |
|---|---|
| oi oi | train: oi |
| meu pedido ainda nao chegou | dev: meu pedido nao chegou ainda |
| qual o status do meu pedido | train: status do pedido |
| meu pagamento caiu? | train: o pagamento caiu? |
| quero solicitar a devolução | train: solicitar devolução |
| quero cancelar o pedido | train: quero cancelar meu pedido |
| quero cancelar antes de enviar | train: dá para cancelar antes de enviar? |
| cancelar compra | train: cancelar a compra |
| abrem sábado? | train: vocês abrem sábado? |
| horário de atendimento por favor | train: qual o horário de atendimento |
| atendente por favor | train: preciso de um atendente |
| tchau tchau | train: tchau |

Two dev phrases had the same problem against training: "qual a situação do meu pedido" (train: "situação do pedido") and "quero falar com atendente" (train: "falar com atendente"). The reported test accuracy therefore included phrases the model had, in effect, already seen.

## Decision

- Overlap is measured in the representation the model uses. Two phrases leak when they have the same set of words after normalization and stopword removal (order and repetition ignored), or when the TF-IDF cosine between them, with the weights of the trained model, is 0.95 or more.
- The dev split is checked against the training examples. The test split is checked against the training examples and the dev split. A phrase that leaks is removed from the later set (test before dev, dev before training), so the knowledge base never changes to make a split pass.
- The 12 test phrases and 2 dev phrases above were removed by this rule, without looking at whether the model got them right. No phrase was added or reworded. The test split is now 109 in-scope and 16 off-topic phrases; the dev split is 61 and 10.
- `evaluation.overlaps` implements the rule; a test runs it on the bundled data and must find nothing, another test feeds it repeated words, reordered words, stopword-only differences and near-duplicates. The evidence command refuses to run when anything leaks, and `metricas.json` records the cosine limit.
- The reports say "held-out phrases" instead of "never-seen phrases": the rule guarantees that no test phrase is the same model input as a training or dev phrase, not that the author never wrote something similar.

## Consequences

- The test numbers drop and become honest; the README and the cards were updated with the new values.
- The 0.95 limit is a judgment call. At this limit the rule found only exact word-set matches in the bundled data; a stricter limit would start removing genuine paraphrases that share most of their content words, which the test split is meant to contain.
- Every future knowledge base edit can create a new leak (a new training example equal to a test phrase). The test fails in that case, and the fix is to remove the phrase from the split, never to drop the training example to keep the number.
