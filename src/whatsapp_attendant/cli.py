"""Command line: evidence, serve, health and check-config.

    python -m whatsapp_attendant evidence [--seed 42] [--conversations 300] [--out evidencia]
    python -m whatsapp_attendant serve [--host 127.0.0.1] [--port 8000] [--demo] [--config FILE]
    python -m whatsapp_attendant health [--url http://127.0.0.1:8000] [--config FILE]
    python -m whatsapp_attendant check-config FILE

Exit codes: 0 success, 1 check failed, 2 usage or configuration error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import httpx

from .config import ConfigError, Settings, load_settings
from .knowledge import KnowledgeBaseError, load_knowledge_base
from .providers import LocalProvider


def _evidence(args: argparse.Namespace) -> int:
    from . import evidence

    metrics = evidence.write(args.out, seed=args.seed, conversations=args.conversations)
    sim, test = metrics["simulation"], metrics["test"]
    print(
        json.dumps(
            {
                "out": args.out,
                "seed": args.seed,
                "conversations": sim["conversations"],
                "resolution_rate": sim["resolution_rate"],
                "handoff_rate": sim["handoff_rate"],
                "test_in_scope_accuracy": test["in_scope_accuracy"],
                "test_out_of_scope_rejection_rate": test["out_of_scope_rejection_rate"],
            }
        )
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    settings = load_settings(args.config)
    if args.demo:
        settings = settings.model_copy(
            update={"demo": settings.demo.model_copy(update={"enabled": True})}
        )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0


def _local_health(settings: Settings) -> dict[str, bool]:
    from .api import self_test

    kb = load_knowledge_base(settings.knowledge_base)
    return {
        "knowledge_base": len(kb.intents) > 0,
        "classifier_self_test": self_test(LocalProvider(kb, settings.engine)),
    }


def _health(args: argparse.Namespace) -> int:
    if args.url:
        try:
            response = httpx.get(args.url.rstrip("/") + "/health", timeout=args.timeout)
        except httpx.HTTPError as exc:
            print(json.dumps({"status": "fail", "error": type(exc).__name__}))
            return 1
        print(response.text)
        return 0 if response.status_code == 200 else 1
    try:
        checks = _local_health(load_settings(args.config))
    except (ConfigError, KnowledgeBaseError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1
    ok = all(checks.values())
    print(json.dumps({"status": "ok" if ok else "fail", "checks": checks}))
    return 0 if ok else 1


def _check_config(args: argparse.Namespace) -> int:
    settings = load_settings(args.file)
    load_knowledge_base(settings.knowledge_base)
    print(json.dumps({"status": "ok", "file": args.file}))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whatsapp-attendant", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evidence", help="build evidencia/ from a seeded run")
    ev.add_argument("--seed", type=int, default=42)
    ev.add_argument("--conversations", type=int, default=300)
    ev.add_argument("--out", default="evidencia")
    ev.set_defaults(func=_evidence)
    sv = sub.add_parser("serve", help="run the webhook server")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--demo", action="store_true", help="enable /console and /dashboard")
    sv.add_argument("--config", default=None)
    sv.set_defaults(func=_serve)
    hc = sub.add_parser("health", help="exit 0 when healthy, 1 otherwise")
    hc.add_argument("--url", default=None, help="check a running server instead of the files")
    hc.add_argument("--timeout", type=float, default=5.0)
    hc.add_argument("--config", default=None)
    hc.set_defaults(func=_health)
    cc = sub.add_parser("check-config", help="validate a config file and its knowledge base")
    cc.add_argument("file")
    cc.set_defaults(func=_check_config)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, KnowledgeBaseError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr
        )
        return 2
