"""Modo alternativo: la interfaz se abre en una ventana de Microsoft Edge (sin barra de direcciones)
y habla con un servidor local. Se usa si la ventana integrada (pywebview) no puede arrancar."""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .api import Api

ROOT = Path(__file__).resolve().parent / "web"
API = Api()
PUBLIC = {n for n in dir(API) if not n.startswith("_") and callable(getattr(API, n))}
UPLOADS = Path(tempfile.gettempdir()) / "HerramientasPDF_subidas"
LAST_PING = [0.0]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        f = ROOT / ("index.html" if path in ("/", "") else path.lstrip("/"))
        if not f.is_file() or (ROOT not in f.resolve().parents and f.resolve() != ROOT):
            return self._send(404, b"no encontrado", "text/plain")
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.replace(b"<!--DEV-->", b"<script>window.__DEV__=true;window.__PING__=true</script>")
        self._send(200, data, mimetypes.guess_type(str(f))[0] or "application/octet-stream")

    def do_POST(self):
        if self.path.startswith("/ping"):
            LAST_PING[0] = time.time()
            return self._send(200, b"{}")
        n = int(self.headers.get("Content-Length", 0))
        if self.path.startswith("/upload"):
            name = os.path.basename(urllib.parse.unquote(self.path.split("name=", 1)[-1])) or "archivo"
            UPLOADS.mkdir(parents=True, exist_ok=True)
            d = Path(tempfile.mkdtemp(dir=UPLOADS))
            dest = d / name
            left = n
            with open(dest, "wb") as out:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    out.write(chunk)
                    left -= len(chunk)
            return self._send(200, json.dumps({"result": str(dest)}).encode())
        name = self.path.split("/api/")[-1]
        if name not in PUBLIC:
            return self._send(404, b'{"error":"no existe"}')
        args = json.loads(self.rfile.read(n) or b"[]")
        try:
            self._send(200, json.dumps({"result": getattr(API, name)(*args)}).encode())
        except Exception as e:
            self._send(200, json.dumps({"error": str(e)}).encode())


def _find_browser():
    cands = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
            cands.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("google-chrome")


def run_app() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    exe = _find_browser()
    if not exe:
        import webbrowser

        webbrowser.open(url)
        print("Abierto en tu navegador. Cierra esta ventana para salir.")
        threading.Event().wait()
        return
    profile = Path(os.environ.get("APPDATA", tempfile.gettempdir())) / "HerramientasPDF" / "ventana"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1240,820",
                      "--no-first-run", "--disable-features=Translate"])
    # El proceso de Edge puede cerrarse al instante y seguir la ventana abierta, asi que
    # el programa se mantiene vivo mientras la ventana siga avisando ("ping") y sale al cerrarla.
    start = time.time()
    while True:
        time.sleep(1)
        if LAST_PING[0]:
            if time.time() - LAST_PING[0] > 10:
                break
        elif time.time() - start > 90:
            break
    shutil.rmtree(UPLOADS, ignore_errors=True)
