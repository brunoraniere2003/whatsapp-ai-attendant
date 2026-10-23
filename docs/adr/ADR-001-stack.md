# ADR-001: Stack do projeto AI WhatsApp Attendant

Status: aceito
Data: 2026-10-22

## Contexto

Projeto criado a partir do template de projeto, tipo `fastapi`.

## Decisão

Python 3.13 com uv (dependências e ambiente), ruff (lint e formato), pytest com cobertura, prek para os ganchos de commit e CI no GitHub Actions. API em FastAPI.

## Consequências

- Mudanças no padrão chegam por `copier update`.
- Qualquer dependência nova de runtime pede um ADR.

## Revisitar quando

O cliente exigir outra stack ou o projeto passar a precisar de build.
