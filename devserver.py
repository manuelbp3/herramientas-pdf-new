"""Modo de pruebas: sirve la interfaz en el navegador (http://127.0.0.1:8765) usando las mismas herramientas.

Sirve para probar sin crear el .exe. No es la aplicación final.
    python devserver.py
"""
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.api import Api

ROOT = Path(__file__).resolve().parent / "app" / "web"
API = Api()
PUBLIC = {n for n in dir(API) if not n.startswith("_") and callable(getattr(API, n))}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        f = ROOT / ("index.html" if path in ("/", "") else path.lstrip("/"))
        if not f.is_file() or ROOT not in f.resolve().parents and f.resolve() != ROOT:
            return self._send(404, b"no encontrado", "text/plain")
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.replace(b"<!--DEV-->", b"<script>window.__DEV__=true</script>")
        self._send(200, data, mimetypes.guess_type(str(f))[0] or "application/octet-stream")

    def do_POST(self):
        name = self.path.split("/api/")[-1]
        if name not in PUBLIC:
            return self._send(404, b'{"error":"no existe"}')
        n = int(self.headers.get("Content-Length", 0))
        args = json.loads(self.rfile.read(n) or b"[]")
        try:
            res = getattr(API, name)(*args)
            self._send(200, json.dumps({"result": res}).encode())
        except Exception as e:
            self._send(200, json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Abre http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
