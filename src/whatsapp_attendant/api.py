"""API do pacote whatsapp-ai-attendant."""

from __future__ import annotations

from fastapi import FastAPI

from whatsapp_attendant import DESCRICAO, NOME

app = FastAPI(title=NOME, description=DESCRICAO)


@app.get("/saude")
def saude() -> dict[str, str]:
    """Responde se a API está no ar."""
    return {"status": "ok"}
