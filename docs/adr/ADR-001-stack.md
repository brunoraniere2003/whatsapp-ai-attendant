# ADR-001: Stack

Status: accepted
Date: 2026-10-22

## Context

The project starts from the team's Copier template, variant `fastapi`. It must run on a laptop and in CI without a GPU, without paid services and without network access in the tests.

## Decision

- Python 3.13, managed by uv (environment, lockfile and dev tools pinned in `uv.lock`).
- FastAPI for the webhook and the demo pages; httpx for the Graph API sender.
- The intent engine is plain Python (no scikit-learn, no model download): the knowledge base is small and the code stays readable.
- Pydantic v2 models with `extra="forbid"` validate the configuration and the knowledge base.
- The Anthropic SDK is an optional extra (`.[llm]`), installed in the dev group only so the tests can build a client.
- ruff for lint and format, pytest with pytest-cov (branch coverage, floor 90%), prek running the pre-commit hooks (ruff, gitleaks, conventional commits), GitHub Actions on Ubuntu (the production OS).
- A single version in `src/whatsapp_attendant/__init__.py`, read by hatchling.

## Consequences

- Template updates arrive through `copier update`.
- A new runtime dependency needs an ADR.

## Revisit when

The knowledge base grows to hundreds of intents, or a client requires another stack.
