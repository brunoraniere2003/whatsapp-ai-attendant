# AI WhatsApp Attendant

WhatsApp Cloud API webhook with a local intent engine, slot filling, human handoff and a learning queue.

## Como rodar

```bash
uv sync
uv run pytest
```

Servidor local: `uv run fastapi dev src/whatsapp_attendant/api.py` e abra `http://127.0.0.1:8000/docs`.

## Documentação

- Spec: `docs/specs/SPEC-001-whatsapp-ai-attendant.md`
- Decisões: `docs/adr/`
- Mudanças: `CHANGELOG.md`
