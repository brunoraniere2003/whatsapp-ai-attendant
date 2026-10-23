# AI WhatsApp Attendant

A WhatsApp Cloud API webhook that answers the common questions of an online store on its own, asks for the order number when it needs one, hands the conversation to a person when it should, and turns every misunderstood message into material for the next version of its knowledge base.

Demo case: fictional data, built as a portfolio project.

Python 3.13 · FastAPI · WhatsApp Cloud API · TF-IDF intent engine · optional Claude second layer · MIT license ([LICENSE](LICENSE))

![Conversation console](vitrine/tela-1.png)

## Problem

A store that sells online receives the same few questions on WhatsApp all day: where is my order, send me the payment slip again, did my payment go through, how do I return this, can I cancel, what time do you open. A person answering them by hand is slow at night and expensive by day. A bot that answers everything is worse: a confident wrong answer to "cancel my order" costs more than a polite "let me pass you to someone".

The hard parts are not the replies. They are knowing when the bot did not understand, collecting the order number without getting stuck, never answering twice when Meta redelivers an event, refusing forged calls, and measuring all of this honestly before a real customer sees it.

## What it does

- **Cloud API webhook.** `GET /webhook` answers Meta's verification, `POST /webhook` checks the `X-Hub-Signature-256` HMAC, ignores redelivered message ids and answers text, button and list replies. Media messages get a polite request for text. Replies go out after the HTTP response, and only network errors and HTTP 408, 425, 429, 500, 502, 503 and 504 are retried, with exponential backoff.
- **Local intent engine.** TF-IDF over words and character trigrams, trained in milliseconds from an editable knowledge base (9 intents in Brazilian Portuguese). Trigrams survive the way people type on a phone: no accents, abbreviations, missing letters. Messages below a confidence threshold are rejected instead of guessed.
- **Dialogue rules.** One session per phone. Intents that need an order number ask for it, re-ask on a wrong reply and answer when it arrives; a number already in the message is used at once. A confident new topic leaves the pending question. Two failed turns in a row, or a request for a person, hand the conversation to a human, and the bot goes silent.
- **Learning queue.** Every message the engine rejects is kept, with the phone masked and the engine's best guess, so the team can approve it as a new example.
- **Optional LLM second layer.** With `ANTHROPIC_API_KEY` set, only messages the local engine rejected go to Claude, with the order number masked, and the answer is constrained by a JSON schema whose intent is an enum of the known intents. Without the key nothing leaves the machine.
- **Operations.** Strict TOML configuration, secrets only from the environment, JSON logs to a rotating file with masked phones, `/health` and a `health` command that exit non-zero on failure, `/metrics` with counters and p50/p95 latency.
- **Evidence.** One command runs a seeded evaluation and writes `evidencia/metricas.json`, an English and a Portuguese report and sample transcripts. A demo console and dashboard show the same engine running.

## How to run

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                             # creates .venv with the dev tools
uv run pytest --cov                                 # 100+ tests, no network, coverage floor 90%
uv run python -m whatsapp_attendant evidence        # rebuilds evidencia/ (seed 42, 300 conversations)
uv run python -m whatsapp_attendant serve --demo    # http://127.0.0.1:8000/console and /dashboard
```

On Windows without uv on the path, the same commands run with `.venv\Scripts\python -m ...`. `python tasks.py check` runs lint, format check, tests with coverage and the evidence check in one go.

Try the webhook locally with a Cloud API payload:

```bash
export WA_VERIFY_TOKEN=change-me
uv run python -m whatsapp_attendant serve
curl "http://127.0.0.1:8000/webhook?hub.mode=subscribe&hub.verify_token=change-me&hub.challenge=42"
curl -X POST http://127.0.0.1:8000/webhook -H "content-type: application/json" -d '{"entry":[{"changes":[{"value":{"messages":[{"from":"5511900000001","id":"wamid.1","type":"text","text":{"body":"cadê meu pedido 482915?"}}]}}]}]}'
curl http://127.0.0.1:8000/metrics
uv run python -m whatsapp_attendant health --url http://127.0.0.1:8000   # exit 0 or 1
```

### Configuration and secrets

Tunables live in a TOML file; [config.example.toml](config.example.toml) documents every key and is tested to equal the built-in defaults. Pass it with `--config` or `ATTENDANT_CONFIG`. Unknown keys and out-of-range values stop the service with a message that names the key (`python -m whatsapp_attendant check-config FILE`). The knowledge base is [knowledge_base.toml](src/whatsapp_attendant/data/knowledge_base.toml), validated the same way.

| Variable | Used for | Without it |
|---|---|---|
| `WA_VERIFY_TOKEN` | webhook verification | verification always answers 403 |
| `WA_APP_SECRET` | HMAC check of every event | events are accepted unsigned (local tests only) |
| `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID` | sending through the Graph API | replies are recorded in memory, nothing is sent |
| `ANTHROPIC_API_KEY` | optional LLM second layer (`pip install .[llm]`) | local engine only, no outbound call |

## Architecture

```mermaid
flowchart LR
    WA[WhatsApp Cloud API] -->|POST /webhook| SIG{HMAC valid?}
    SIG -->|no| E401[401]
    SIG -->|yes| IDEM{message id seen?}
    IDEM -->|yes| DUP[skip and count]
    IDEM -->|no| ATT[Attendant<br/>session per phone]
    ATT --> MASK[mask order number]
    MASK --> NLU[TF-IDF classifier<br/>words + char trigrams]
    NLU -->|rejected and key set| LLM[Claude<br/>JSON schema enum]
    ATT <--> KB[(knowledge_base.toml)]
    ATT <--> ORD[OrderBackend port<br/>fake in the demo]
    ATT -->|not understood| LQ[(learning queue)]
    ATT -->|handoff| HUM[human agent]
    ATT -->|reply| BG[background send]
    BG --> GRAPH[Graph API<br/>retry transient errors]
```

The design keeps the expensive and unpredictable parts at the edge. The local engine decides most messages in well under a millisecond and can be tested offline; the LLM is a fallback for what the engine rejects, never a dependency. Every external system sits behind a small interface (`IntentProvider`, `Sender`, `OrderBackend`), so a real ERP, Twilio or another LLM provider is one class, not a rewrite. Decisions are recorded in [docs/adr](docs/adr): [stack](docs/adr/ADR-001-stack.md), [local engine first](docs/adr/ADR-002-local-intent-engine.md), [in-memory state](docs/adr/ADR-003-in-memory-state.md) and [evaluation protocol](docs/adr/ADR-004-evaluation-protocol.md).

| Path | What is there |
|---|---|
| [src/whatsapp_attendant](src/whatsapp_attendant) | `api` (webhook, health, metrics), `whatsapp` (payloads, signature, sender), `dialogue` (rules), `nlu` (classifier), `providers` (local and LLM), `knowledge`, `config`, `store`, `logs`, `metrics` |
| [src/whatsapp_attendant/data](src/whatsapp_attendant/data) | knowledge base, dev split and frozen test split |
| `evaluation.py`, `simulation.py`, `evidence.py`, `report.py` | evaluation, seeded simulation and reports |
| [evidencia](evidencia) | `metricas.json`, reports in English and Portuguese, transcripts, benchmark |
| [docs](docs) | [spec](docs/specs/SPEC-001-whatsapp-ai-attendant.md), ADRs, [runbooks](docs/runbooks/README.md), [operations](docs/operations.md) (SLOs, RACI, risks, roadmap) |
| [vitrine](vitrine) | portfolio cards, covers and screens, with the generator in `vitrine/src` |
| [CHANGELOG.md](CHANGELOG.md) | release notes (Keep a Changelog, SemVer) |

## Results

All numbers come from `evidencia/metricas.json`, produced by `python -m whatsapp_attendant evidence` with seed 42. A test regenerates it and fails if it differs from the committed file.

| Measure | Value | How it was measured |
|---|---|---|
| Conversations resolved with the right answer | **72.0%** (216 of 300) | 300 simulated conversations; resolved only when the bot answered the customer's real main question with no handoff |
| Same, without the 23 customers who asked for a person | 78.0% (216 of 277) | excludes conversations whose main question was "talk to a person" |
| Handed to a person | 7.0% (21) | 17 on request, 4 after two failed turns in a row |
| Answered a different question | 21.0% (63) | the bot was confident and wrong; counted as a failure, not as resolved |
| Intent accuracy on never-seen phrases | **86.8%** (105 of 121) | frozen test split, committed before any evaluation code existed |
| Macro F1 on the test split | 0.87 | per intent from 0.74 (cancellation) to 0.92 |
| Off-topic messages rejected | 62.5% (10 of 16) | the rest got a wrong intent; four were taken as a cancellation |
| Confidence threshold | 0.16 | chosen on the dev split (93.2% accuracy there); the test split was not used |

How the numbers were protected: the classifier learns only from the 110 knowledge base examples; a dev split of 73 phrases chose the threshold and guided edits of the examples; the test split of 137 phrases (121 in scope, 16 off topic) was committed before the evaluation code and only shrank when a leakage rule removed 5 phrases that repeated training examples. A test asserts that no normalized phrase appears in two of the three sets. Simulated customers draw their messages from the test split and add typos, filler words and order numbers at random. The drop from 95.2% in-scope accuracy on dev to 86.8% on test is the expected cost of choosing on one set and reporting on another.

Latency on the development machine was 0.14 ms at p50 and 0.22 ms at p95 per message for the local engine ([benchmark.json](evidencia/benchmark.json), machine dependent and kept out of `metricas.json`). Full report: [evidencia/report.html](evidencia/report.html), in Portuguese [evidencia/relatorio.html](evidencia/relatorio.html).

![Evaluation dashboard](vitrine/tela-2.png)

## Limitations

- **Simulated, not real traffic.** One author wrote the examples and both evaluation splits. 121 test phrases give an uncertainty of roughly 6 points on the accuracy. Real messages from the store are the first thing to collect.
- **One conversation in five gets a confident wrong answer.** The threshold that maximized dev accuracy is low, so the engine prefers answering to rejecting. The LLM layer only sees rejected messages, so it does not fix these. The next step is a confirmation question in the low-confidence band, measured against this baseline.
- **Off-topic rejection is weak (62.5%).** "Cancel my phone plan" looks like an order cancellation. More off-topic examples or a margin rule between the top two intents would help; neither is in this version.
- **The LLM layer is not evaluated.** It is tested with a fake client only, because a real run needs a key and costs money.
- **State lives in memory.** Sessions, idempotency ids and the learning queue are lost on restart and are not shared between replicas (ADR-003). Production needs Redis or a database behind the same interfaces.
- **No real store behind it.** The order lookup is a deterministic fake; payment slips and invoices are not really sent.
- **Brazilian Portuguese only, text only.** Another language needs its own examples and evaluation; audio and images are answered with a request for text.
- **Graph API version.** The default `v23.0` must be checked against Meta's current version before going live.

## Resumo em português

Case demonstrativo com dados fictícios. Webhook da WhatsApp Cloud API para uma loja virtual fictícia: entende a dúvida do cliente com um motor de intenções local (TF-IDF com trigramas de caracteres, robusto a erro de digitação), pede o número do pedido quando precisa, transfere para um atendente depois de duas falhas seguidas ou a pedido do cliente e guarda as mensagens não entendidas numa fila de aprendizado. Tem verificação de assinatura HMAC, idempotência contra reenvio da Meta, reenvio só em erro temporário, logs JSON com telefone mascarado, health check e métricas. Um modelo de linguagem opcional entra só nas mensagens que o motor local recusou.

Em 300 conversas simuladas com semente fixa, 72,0% foram resolvidas pelo robô com a resposta certa e 7,0% foram para um atendente. O acerto de intenção foi de 86,8% em 121 frases que nunca entraram no treino. Os números, os limites e a forma de medir estão nas seções acima e no relatório em português ([evidencia/relatorio.html](evidencia/relatorio.html)).
