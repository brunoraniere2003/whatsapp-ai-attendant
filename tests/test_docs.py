"""Docs as code: the documents are tested like the code they describe."""

import json
import re

import pytest
from conftest import ROOT

from whatsapp_attendant import __version__

README = (ROOT / "README.md").read_text(encoding="utf-8")
SECTIONS = (
    "## Problem",
    "## What it does",
    "## How to run",
    "## Architecture",
    "## Results",
    "## Limitations",
)
RUNBOOK_SECTIONS = (
    "Symptom",
    "Detection",
    "Diagnosis",
    "Mitigation",
    "Fix",
    "Prevention",
    "Owner",
)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _markdown_files():
    skip = {".venv", ".git", ".pytest_cache", ".ruff_cache", "node_modules"}
    return [p for p in ROOT.rglob("*.md") if not skip & set(p.relative_to(ROOT).parts)]


def test_readme_has_the_required_sections_in_order():
    headings = re.findall(r"^## .+$", README, re.M)
    positions = [headings.index(s) for s in SECTIONS]
    assert positions == sorted(positions)
    assert headings[-1] == "## Resumo em português"


def test_readme_carries_the_demo_seal_in_both_languages():
    top = "\n".join(README.splitlines()[:8])
    assert "Demo case: fictional data, built as a portfolio project." in top
    summary = README.split("## Resumo em português", 1)[1]
    assert "Case demonstrativo com dados fictícios." in summary


def test_readme_results_match_the_metrics():
    m = json.loads((ROOT / "evidencia" / "metricas.json").read_text(encoding="utf-8"))
    sim, test = m["simulation"], m["test"]
    for fraction in (
        sim["resolution_rate"],
        sim["handoff_rate"],
        sim["misrouted_rate"],
        test["in_scope_accuracy"],
        test["out_of_scope_rejection_rate"],
    ):
        assert f"{fraction * 100:.1f}%" in README
    assert f"{sim['outcomes']['resolved']} of {sim['conversations']}" in README
    assert f"{test['in_scope_correct']} of {test['in_scope_total']}" in README
    assert f"{m['config']['confidence_threshold']}" in README


def test_changelog_version_matches_the_package():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Keep a Changelog" in text and "## [Unreleased]" in text
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", text, re.M)
    assert releases and releases[0] == __version__


def test_license_is_mit_for_the_author():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 Bruno Raniere" in text


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(path):
    broken = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (path.parent / target.split("#", 1)[0]).exists():
            broken.append(target)
    assert not broken, f"{path.name}: {broken}"


@pytest.mark.parametrize(
    "path",
    [p for p in (ROOT / "docs" / "runbooks").glob("*.md") if p.name != "README.md"],
    ids=lambda p: p.name,
)
def test_runbooks_have_every_section(path):
    headings = set(re.findall(r"^## (.+)$", path.read_text(encoding="utf-8"), re.M))
    assert set(RUNBOOK_SECTIONS) <= headings


def test_every_acceptance_criterion_has_a_test_and_vice_versa():
    spec = next((ROOT / "docs" / "specs").glob("SPEC-001-*.md")).read_text(encoding="utf-8")
    criteria = set(re.findall(r"^### CA-(\d+):", spec, re.M))
    tests = set()
    for file in (ROOT / "tests").glob("test_*.py"):
        tests |= set(re.findall(r"^def test_ca_(\d+)_", file.read_text(encoding="utf-8"), re.M))
    assert criteria == tests
