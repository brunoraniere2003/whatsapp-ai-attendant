"""Portfolio cards and images (CA-13): the same rules the factory gate applies."""

import importlib.util
import json
import re
import struct
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest
from conftest import ROOT

VITRINE = ROOT / "vitrine"
CARDS = {"pt": VITRINE / "card.pt.md", "en": VITRINE / "card.en.md"}
IMAGES = ("capa-pt.png", "capa-en.png", "tela-1.png", "tela-2.png")
DASHES = re.compile("[\u2012\u2013\u2014\u2015\u2e3a\u2e3b]")
EMOJI = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\u2b00-\u2bff\u2190-\u21ff\ufe0f\u200d]")
MARKDOWN = re.compile(r"(\*\*[^*]+\*\*|^#{1,6}\s|`)", re.M)
LINKS = re.compile(r"(https?://|www\.|\.com\b|\.br\b|@)", re.I)
NUMBER = re.compile(r"(?<![^\W_])(?<!\d[.,])(?>\d+(?:[.,]\d+)?)(?:(?=[xX](?![^\W_]))|(?![^\W_]))")


def _card(lang: str) -> tuple[str, str, list[str]]:
    lines = CARDS[lang].read_text(encoding="utf-8").strip().split("\n")
    extra = [line for line in lines if line.startswith(("Role:", "Skills:"))]
    body = "\n".join(line for line in lines[1:] if line not in extra).strip()
    return lines[0], body, extra


def _metric_values(data) -> list[Decimal]:
    if isinstance(data, bool):
        return []
    if isinstance(data, int | float):
        return [Decimal(repr(data))]
    if isinstance(data, dict):
        return [v for item in data.values() for v in _metric_values(item)]
    if isinstance(data, list):
        return [v for item in data for v in _metric_values(item)]
    return []


def _has_evidence(raw: str, values: list[Decimal]) -> bool:
    number = Decimal(raw.replace(",", "."))
    places = len(raw.replace(",", ".").partition(".")[2])
    step = Decimal(1).scaleb(-places)
    return any(
        candidate.quantize(step, rounding=mode) == number
        for value in values
        for candidate in (value, value * 100)
        for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN)
    )


@pytest.mark.parametrize(
    ("lang", "title_max", "body_range"), [("pt", 60, (600, 900)), ("en", 70, (600, 1000))]
)
def test_ca_13_card_shape(lang, title_max, body_range):
    title, body, extra = _card(lang)
    assert 0 < len(title) <= title_max
    assert body_range[0] <= len(body) <= body_range[1]
    if lang == "pt":
        assert "Case demonstrativo com dados fictícios." in body and not extra
    else:
        assert "Demo case" in body
        assert extra[0].startswith("Role: ") and extra[1].startswith("Skills: ")
        assert len(extra[1].removeprefix("Skills: ").split(", ")) >= 3


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_ca_13_card_style(lang):
    text = CARDS[lang].read_text(encoding="utf-8")
    assert not DASHES.search(text) and not EMOJI.search(text) and not MARKDOWN.search(text)
    assert not LINKS.search(text) and text.count("!") <= 1
    if lang == "pt":
        assert not re.search(r"\d\.\d", text), "Brazilian format: decimal comma, no thousands dot"


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_ca_13_card_numbers_exist_in_the_metrics(lang):
    values = _metric_values(json.loads((ROOT / "evidencia" / "metricas.json").read_text("utf-8")))
    numbers = NUMBER.findall(CARDS[lang].read_text(encoding="utf-8"))
    assert numbers and all(_has_evidence(n, values) for n in numbers), numbers


@pytest.mark.parametrize("name", IMAGES)
def test_ca_13_images_are_1600x900_png(name):
    header = (VITRINE / name).read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR"
    assert struct.unpack(">II", header[16:24]) == (1600, 900)


def test_image_generator_is_kept_in_the_repository():
    source = (VITRINE / "src" / "build.py").read_text(encoding="utf-8")
    assert all(name in source for name in IMAGES)


def _build_script():
    spec = importlib.util.spec_from_file_location("vitrine_build", VITRINE / "src" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_image_generator_finds_chromium_from_the_environment_or_the_path(monkeypatch):
    build = _build_script()
    monkeypatch.setenv("CHROME_PATH", "/opt/browser/chrome")
    assert build.find_chrome() == "/opt/browser/chrome"
    monkeypatch.delenv("CHROME_PATH")
    on_path = {"msedge": "/usr/bin/msedge"}
    monkeypatch.setattr(build.shutil, "which", on_path.get)
    assert build.find_chrome() == "/usr/bin/msedge"
    on_path["chromium"] = "/usr/bin/chromium"
    assert build.find_chrome() == "/usr/bin/chromium"
    on_path.clear()
    assert build.find_chrome() is None


def test_image_generator_stops_without_chromium(monkeypatch, capsys):
    build = _build_script()
    monkeypatch.setattr(build, "CHROME", None)
    assert build.main() == 2
    assert "CHROME_PATH" in capsys.readouterr().out
