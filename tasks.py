"""Task runner: python tasks.py {lint,fmt,test,cov,evidence,evidence-check,vitrine,check}.

`check` is what CI runs: lint, format check, tests with coverage and the evidence check.
Uses the interpreter that runs it, so call it with the project's venv (or `uv run`).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(*args: str) -> int:
    print("$", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=False).returncode


def lint() -> int:
    return run(PY, "-m", "ruff", "check", ".") or run(PY, "-m", "ruff", "format", "--check", ".")


def fmt() -> int:
    return run(PY, "-m", "ruff", "check", ".", "--fix") or run(PY, "-m", "ruff", "format", ".")


def test() -> int:
    return run(PY, "-m", "pytest", "-q")


def cov() -> int:
    return run(PY, "-m", "pytest", "-q", "--cov", "--cov-report=term-missing")


def evidence() -> int:
    return run(PY, "-m", "whatsapp_attendant", "evidence")


def evidence_check() -> int:
    """The committed metricas.json must equal a fresh run."""
    with tempfile.TemporaryDirectory() as tmp:
        code = run(PY, "-m", "whatsapp_attendant", "evidence", "--out", tmp)
        if code:
            return code
        fresh = (Path(tmp) / "metricas.json").read_text(encoding="utf-8")
    committed = (ROOT / "evidencia" / "metricas.json").read_text(encoding="utf-8")
    if fresh != committed:
        print("evidencia/metricas.json is stale: run python tasks.py evidence")
        return 1
    print("evidencia/metricas.json matches a fresh run")
    return 0


def vitrine() -> int:
    return run(PY, "vitrine/src/build.py")


def check() -> int:
    for step in (lint, cov, evidence_check):
        code = step()
        if code:
            return code
    return 0


TASKS = {
    "lint": lint,
    "fmt": fmt,
    "test": test,
    "cov": cov,
    "evidence": evidence,
    "evidence-check": evidence_check,
    "vitrine": vitrine,
    "check": check,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in TASKS:
        print(__doc__)
        return 2
    return TASKS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
