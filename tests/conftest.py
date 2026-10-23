"""Shared fixtures. Tests never touch the network or the repository's logs/ folder."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from whatsapp_attendant.config import LoggingSettings, Settings
from whatsapp_attendant.dialogue import Attendant
from whatsapp_attendant.knowledge import load_knowledge_base
from whatsapp_attendant.logs import get_logger
from whatsapp_attendant.providers import LocalProvider

ROOT = Path(__file__).resolve().parent.parent


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeMessages:
    """Stands in for `client.messages` / `client.beta.messages` of the Anthropic SDK."""

    def __init__(self, answer: object = None, stop_reason: str = "end_turn", error=None) -> None:
        self.answer = answer
        self.stop_reason = stop_reason
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
        )


class FakeLLMClient:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages
        self.beta = SimpleNamespace(messages=messages)


@pytest.fixture(scope="session")
def kb():
    return load_knowledge_base()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(logging=LoggingSettings(file=str(tmp_path / "logs" / "attendant.log")))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def attendant(kb, clock) -> Attendant:
    return Attendant(kb, LocalProvider(kb), clock=clock)


@pytest.fixture(autouse=True)
def _close_log_handlers():
    yield
    logger = get_logger()
    for handler in list(logger.handlers):
        if getattr(handler, "_attendant_handler", False):
            logger.removeHandler(handler)
            handler.close()


def read_log(settings: Settings) -> list[dict]:
    path = Path(settings.logging.file)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
