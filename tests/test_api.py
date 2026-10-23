from fastapi.testclient import TestClient

from whatsapp_attendant.api import app


def test_ca_1_saude_responde_ok():
    resposta = TestClient(app).get("/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
