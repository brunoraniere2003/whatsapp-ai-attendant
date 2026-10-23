"""Builds the portfolio images and the PDF evidence with headless Chromium.

    python vitrine/src/build.py            (from the repository root, with the project's venv)

- vitrine/capa-pt.png and vitrine/capa-en.png: covers in the same visual style as the rest of the
  portfolio (HTML rendered at 1600x900).
- vitrine/tela-1.png and vitrine/tela-2.png: real screenshots of the running service (demo UI):
  the conversation console and the evaluation dashboard.
- evidencia/report.pdf, evidencia/relatorio.pdf and evidencia/previa.png from the HTML reports.

Chromium path: $CHROME_PATH, or the first of chromium, chrome or msedge found on the PATH; with
neither it stops and asks for CHROME_PATH. Fails if any image is not 1600x900.
"""

from __future__ import annotations

import html
import os
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "vitrine"
EVIDENCE = ROOT / "evidencia"
# Chromium-based browsers looked up on the PATH when $CHROME_PATH is not set.
CHROME_NAMES = ("chromium", "chrome", "msedge")
SIZE = (1600, 900)


def find_chrome() -> str | None:
    """$CHROME_PATH when set, else the first of CHROME_NAMES on the PATH, else None."""
    explicit = os.environ.get("CHROME_PATH")
    if explicit:
        return explicit
    return next((found for name in CHROME_NAMES if (found := shutil.which(name))), None)


CHROME = find_chrome()

COVERS = {
    "capa-pt.png": {
        "lang": "pt-BR",
        "title": "Atendente de WhatsApp com IA",
        "sub": "Entende o cliente, pede o número do pedido e passa para um atendente "
        "quando precisa",
        "tags": ["Python", "FastAPI", "WhatsApp Cloud API", "NLP", "Claude"],
    },
    "capa-en.png": {
        "lang": "en",
        "title": "AI WhatsApp Attendant",
        "sub": "Understands the customer, asks for the order number and hands off to a person "
        "when needed",
        "tags": ["Python", "FastAPI", "WhatsApp Cloud API", "NLP", "Claude"],
    },
}
COLORS = ("#0d3b3c", "#14786f")

COVER = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>
html,body{{margin:0;width:1600px;height:900px;overflow:hidden}}
body{{background:linear-gradient(180deg,{c1},{c2});font-family:"Segoe UI",Arial,sans-serif;
color:#fff;position:relative}}
.topo{{position:absolute;left:90px;top:120px;right:150px;display:flex}}
.barra{{width:13px;min-height:240px;background:#fff;flex:none}}
.txt{{padding-left:37px}}
h1{{margin:6px 0 0;font-size:76px;line-height:100px;font-weight:700}}
p{{margin:24px 0 0;font-size:38px;line-height:56px;color:#e6edf5;font-weight:300}}
.tags{{position:absolute;left:140px;top:710px;display:flex;gap:24px}}
.tag{{background:#fff;color:{c1};font-weight:700;font-size:34px;padding:8px 24px;
border-radius:34px}}
.nome{{position:absolute;right:120px;bottom:34px;font-size:32px;color:#e6edf5;font-weight:300}}
</style></head><body>
<div class="topo"><div class="barra"></div><div class="txt"><h1>{title}</h1><p>{sub}</p></div></div>
<div class="tags">{tags}</div><div class="nome">Bruno Raniere</div>
</body></html>"""


def chrome(*args: str) -> None:
    base = [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run"]
    subprocess.run([*base, *args], check=True, capture_output=True, timeout=120)


def screenshot(url: str, target: Path, size: tuple[int, int] = SIZE) -> None:
    chrome(
        "--force-device-scale-factor=1",
        f"--window-size={size[0]},{size[1]}",
        "--virtual-time-budget=3000",
        f"--screenshot={target}",
        url,
    )
    print(target.relative_to(ROOT))


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", header[16:24])


def covers(tmp: Path) -> None:
    c1, c2 = COLORS
    for name, cover in COVERS.items():
        page = COVER.format(
            lang=cover["lang"],
            c1=c1,
            c2=c2,
            title=html.escape(cover["title"]),
            sub=html.escape(cover["sub"]),
            tags="".join(f'<span class="tag">{html.escape(t)}</span>' for t in cover["tags"]),
        )
        source = tmp / f"{name}.html"
        source.write_text(page, encoding="utf-8")
        screenshot(source.as_uri(), OUT / name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def screens(tmp: Path) -> None:
    """Run the real app (demo UI on) in a thread and screenshot two of its pages."""
    import uvicorn

    from whatsapp_attendant.api import create_app
    from whatsapp_attendant.config import DemoSettings, LoggingSettings, Secrets, Settings
    from whatsapp_attendant.logs import get_logger

    settings = Settings(
        demo=DemoSettings(enabled=True),
        logging=LoggingSettings(file=str(tmp / "attendant.log")),
    )
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    # A throwaway app secret: the webhook is not used, but /health must be green (fail closed).
    app = create_app(settings, Secrets(app_secret=secrets.token_hex(16)))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("the demo server did not become healthy")
        screenshot(f"{base}/console?scenario=order-status", OUT / "tela-1.png")
        screenshot(f"{base}/dashboard", OUT / "tela-2.png")
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        for handler in list(get_logger().handlers):
            handler.close()


def evidence_files() -> None:
    for name in ("report", "relatorio"):
        source = (EVIDENCE / f"{name}.html").as_uri()
        chrome("--no-pdf-header-footer", f"--print-to-pdf={EVIDENCE / f'{name}.pdf'}", source)
        print(f"evidencia/{name}.pdf")
    screenshot((EVIDENCE / "relatorio.html").as_uri(), EVIDENCE / "previa.png", (1400, 3020))


def main() -> int:
    if CHROME is None or not Path(CHROME).is_file():
        tried = CHROME or f"none of {', '.join(CHROME_NAMES)} is on the PATH"
        print(f"Chromium not found: {tried}. Set CHROME_PATH to a Chromium-based browser.")
        return 2
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        covers(tmp)
        screens(tmp)
    evidence_files()
    wrong = []
    for name in ("capa-pt.png", "capa-en.png", "tela-1.png", "tela-2.png"):
        size = png_size(OUT / name)
        print(f"vitrine/{name}: {size[0]}x{size[1]}")
        if size != SIZE:
            wrong.append(name)
    if wrong:
        print("not 1600x900:", ", ".join(wrong))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
