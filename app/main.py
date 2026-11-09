"""Ventana de la aplicación (pywebview + interfaz HTML)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .api import Api


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def main() -> None:
    try:
        import webview
        import webview.platforms.winforms  # noqa: F401  (falla si falta pythonnet)
    except Exception as ex:
        print("pywebview no disponible, uso Edge:", ex, file=sys.stderr)
        from .server import run_app

        run_app()
        return

    api = Api()
    window = webview.create_window(
        "Herramientas PDF",
        str(web_dir() / "index.html"),
        js_api=api,
        width=1240,
        height=820,
        min_size=(980, 640),
        background_color="#0A0C12",
    )
    api._set_window(window)

    def dark_titlebar():
        """Barra de título oscura en Windows 10/11 (si no se puede, se queda como está)."""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.FindWindowW(None, "Herramientas PDF")
            if hwnd:
                one, col = ctypes.c_int(1), ctypes.c_int(0x00120C0A)
                for attr in (20, 19):
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(one), 4)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), 4)
        except Exception:
            pass

    window.events.shown += dark_titlebar

    def on_drop(e):
        """Archivos arrastrados desde el Explorador: se pasan a la interfaz como rutas."""
        try:
            files = e["dataTransfer"]["files"]
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                window.evaluate_js(f"window.__dropped({json.dumps(paths)})")
        except Exception as ex:  # no romper la app por un arrastre raro
            print("drop:", ex, file=sys.stderr)

    def bind(w):
        try:
            from webview.dom import DOMEventHandler

            noop = lambda e: None
            w.dom.document.events.dragenter += DOMEventHandler(noop, True, True)
            w.dom.document.events.dragstart += DOMEventHandler(noop, True, True)
            w.dom.document.events.dragover += DOMEventHandler(noop, True, True, debounce=300)
            w.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception as ex:
            print("Arrastrar y soltar no disponible:", ex, file=sys.stderr)

    webview.start(bind, window)


if __name__ == "__main__":
    main()
