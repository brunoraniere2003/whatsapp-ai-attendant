import json
import runpy
import sys

import httpx
import pytest

from whatsapp_attendant import cli

ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the host the demo must refuse


def run(capsys, *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_ca_11_health_command_exits_zero_when_healthy(capsys, monkeypatch):
    monkeypatch.delenv("ATTENDANT_CONFIG", raising=False)
    code, out = run(capsys, "health")
    assert code == 0 and json.loads(out)["status"] == "ok"


def test_ca_11_health_command_exits_one_with_a_broken_knowledge_base(capsys, tmp_path):
    config = tmp_path / "c.toml"
    config.write_text(f"knowledge_base = '{tmp_path / 'missing.toml'}'\n", encoding="utf-8")
    code, out = run(capsys, "health", "--config", str(config))
    assert code == 1 and json.loads(out)["status"] == "fail"


def test_ca_11_health_command_can_check_a_running_server(capsys, monkeypatch):
    responses = iter([httpx.Response(200, text='{"status":"ok"}'), httpx.Response(503, text="{}")])
    monkeypatch.setattr(cli.httpx, "get", lambda url, timeout: next(responses))
    assert run(capsys, "health", "--url", "http://127.0.0.1:8000")[0] == 0
    assert run(capsys, "health", "--url", "http://127.0.0.1:8000")[0] == 1

    def refuse(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cli.httpx, "get", refuse)
    code, out = run(capsys, "health", "--url", "http://127.0.0.1:8000")
    assert code == 1 and json.loads(out)["error"] == "ConnectError"


def test_check_config_accepts_the_example_and_rejects_typos(capsys, tmp_path):
    assert run(capsys, "check-config", "config.example.toml")[0] == 0
    bad = tmp_path / "bad.toml"
    bad.write_text("[engine]\nthreshold = 0.3\n", encoding="utf-8")
    assert cli.main(["check-config", str(bad)]) == 2
    assert "engine.threshold" in capsys.readouterr().err


def test_evidence_command_writes_and_summarizes(capsys, tmp_path):
    code, out = run(capsys, "evidence", "--out", str(tmp_path), "--conversations", "10")
    summary = json.loads(out)
    assert code == 0 and summary["conversations"] == 10
    assert (tmp_path / "metricas.json").is_file()


def test_serve_builds_the_app_and_honors_demo(monkeypatch, tmp_path):
    captured = {}

    def fake_run(app, host, port, log_level):
        captured.update(app=app, host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    config = tmp_path / "c.toml"
    config.write_text(f"[logging]\nfile = '{tmp_path / 'a.log'}'\n", encoding="utf-8")
    assert cli.main(["serve", "--demo", "--port", "9001", "--config", str(config)]) == 0
    assert captured["port"] == 9001 and captured["app"].state.rt.settings.demo.enabled
    assert cli.main(["serve", "--config", str(config)]) == 0
    assert not captured["app"].state.rt.settings.demo.enabled


def test_module_entry_point(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["whatsapp_attendant", "health"])
    monkeypatch.delenv("ATTENDANT_CONFIG", raising=False)
    with pytest.raises(SystemExit) as info:
        runpy.run_module("whatsapp_attendant", run_name="__main__")
    assert info.value.code == 0


@pytest.mark.parametrize(
    ("host", "extra", "code"),
    [
        (ALL_INTERFACES, [], 2),
        ("192.168.0.10", [], 2),
        (ALL_INTERFACES, ["--allow-remote-demo"], 0),
        ("localhost", [], 0),
        ("::1", [], 0),
        ("127.0.0.2", [], 0),
    ],
)
def test_ca_13_serve_demo_stays_on_loopback_unless_allowed(
    monkeypatch, tmp_path, capsys, host, extra, code
):
    started = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port, log_level: started.append(host))
    config = tmp_path / "c.toml"
    config.write_text(f"[logging]\nfile = '{tmp_path / 'a.log'}'\n", encoding="utf-8")
    argv = ["serve", "--demo", "--host", host, "--config", str(config), *extra]
    assert cli.main(argv) == code
    assert started == ([host] if code == 0 else [])
    if code:
        assert "--allow-remote-demo" in capsys.readouterr().err
