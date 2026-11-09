"""Puente entre la interfaz (HTML) y las herramientas (core).

Todos los métodos públicos de `Api` se pueden llamar desde JavaScript.
Lo privado (con guion bajo) no se expone.
"""
from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from PIL import Image, ImageOps

from . import core, render


def _data_url(img: Image.Image, fmt="JPEG", quality=72) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        mime = "image/jpeg"
    else:
        img.save(buf, "PNG")
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


class Api:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._prog = {"running": False, "done": 0, "total": 0, "msg": ""}

    def _set_window(self, window):
        self._window = window

    # ───────────── información y diálogos ─────────────
    def info(self):
        return {
            "downloads": str(core.downloads_dir()),
            "office": bool(core.find_soffice()),
            "ocr": core.ocr_available(),
            "ocr_langs": core.ocr_languages(),
            "render": render.available(),
            "heic": core.HEIC_OK,
            "platform": sys.platform,
        }

    def pick_files(self, exts, multiple=True):
        """Abre el selector de archivos de Windows. Devuelve una lista de rutas."""
        if self._window is None:
            return self._pick_tk(exts, multiple)
        import webview

        exts = [e.lstrip(".") for e in (exts or [])]
        pats = ";".join(f"*.{e}" for e in exts) if exts else "*.*"
        types = (f"Archivos compatibles ({pats})", "Todos los archivos (*.*)")
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        res = self._window.create_file_dialog(kind, allow_multiple=bool(multiple), file_types=types)
        return [str(p) for p in (res or [])]

    def _pick_tk(self, exts, multiple):
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            exts = [e.lstrip(".") for e in (exts or [])]
            pats = " ".join(f"*.{e}" for e in exts) if exts else "*.*"
            kw = {"filetypes": [("Archivos compatibles", pats), ("Todos los archivos", "*.*")]}
            res = filedialog.askopenfilenames(**kw) if multiple else filedialog.askopenfilename(**kw)
            root.destroy()
            return [str(x) for x in ([res] if isinstance(res, str) and res else res)] if res else []
        except Exception:
            return []

    def file_info(self, path):
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "No encuentro el archivo."}
        e = core.ext_of(p)
        out = {"ok": True, "path": str(p), "name": p.name, "ext": e, "size": p.stat().st_size,
               "size_text": core.fmt_size(p.stat().st_size)}
        if e == "pdf":
            try:
                out["encrypted"] = core.pdf_is_encrypted(p)
                out["pages"] = None if out["encrypted"] else core.page_count(p)
            except core.ToolError as ex:
                out["error"] = str(ex)
        return out

    def form_fields(self, path):
        """Campos rellenables de un PDF (para la herramienta «Rellenar formulario»)."""
        try:
            from . import extra
            return {"ok": True, "fields": extra.form_fields(path)}
        except core.ToolError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo leer el formulario: {e}"}

    def preview(self, path, width=150):
        """Miniatura de un PDF (primera página) o de una imagen."""
        try:
            e = core.ext_of(path)
            if e == "pdf":
                if core.pdf_is_encrypted(path):
                    return None
                return _data_url(render.render_width(path, 0, int(width)))
            if e in ("jpg", "png", "webp", "bmp", "tiff", "gif", "heic"):
                im = ImageOps.exif_transpose(Image.open(path))
                im.thumbnail((int(width) * 2, int(width) * 2))
                if e in ("png", "webp", "gif") and im.mode in ("RGBA", "LA", "P"):
                    return _data_url(im.convert("RGBA"), fmt="PNG")
                return _data_url(im)
        except Exception:
            return None
        return None

    def thumbs(self, path, start, count, width=170):
        try:
            return [_data_url(im, quality=70) for im in render.render_many_width(path, int(start), int(count), int(width))]
        except Exception as ex:
            return {"error": str(ex)}

    def page_image(self, path, index, width=900):
        try:
            im = render.render_width(path, int(index), int(width))
            return {"data": _data_url(im, quality=85), "w": im.width, "h": im.height}
        except Exception as ex:
            return {"error": str(ex)}

    # ───────────── firmas guardadas ─────────────
    def list_signatures(self):
        out = []
        for sid in core.list_signatures():
            p = core.signature_path(sid)
            if p:
                im = Image.open(p)
                out.append({"id": sid, "data": _data_url(im, "PNG"), "w": im.width, "h": im.height})
        return out

    def save_signature(self, data_url):
        try:
            return {"ok": True, "id": core.save_signature_dataurl(data_url)}
        except core.ToolError as e:
            return {"ok": False, "error": str(e)}

    def import_signature(self):
        files = self.pick_files(["png", "jpg", "jpeg", "bmp", "webp"], False)
        if not files:
            return {"ok": False, "cancelled": True}
        try:
            return {"ok": True, "id": core.save_signature_from_file(files[0])}
        except core.ToolError as e:
            return {"ok": False, "error": str(e)}

    def delete_signature(self, sid):
        core.delete_signature(sid)
        return True

    # ───────────── ejecutar herramientas ─────────────
    def progress(self):
        with self._lock:
            return dict(self._prog)

    def _set(self, **kw):
        with self._lock:
            self._prog.update(kw)

    def _cb(self, done, total, msg=""):
        self._set(msg=msg)

    def run(self, tool, files, options=None):
        options = dict(options or {})
        files = [str(f) for f in (files or [])]
        fn = core.TOOLS.get(tool)
        if fn is None:
            return {"ok": False, "outputs": [], "messages": [], "errors": ["Herramienta desconocida."], "folder": None}
        out_dir = core.downloads_dir()
        outputs, messages, errors, folder = [], [], [], None
        self._set(running=True, done=0, total=max(1, len(files)), msg="Preparando…")
        try:
            if tool == "edit":
                for it in options.get("items", []):
                    if it.get("sig"):
                        it["image"] = core.signature_path(it["sig"])
            if tool in core.COMBINE:
                res = fn(files, out_dir=out_dir, progress=self._cb, **options)
                outputs += res["outputs"]; messages.append(res["message"]); folder = res.get("folder") or folder
            elif tool in core.SINGLE:
                if not files:
                    raise core.ToolError("Elige un archivo.")
                res = fn(files[0], out_dir=out_dir, progress=self._cb, **options)
                outputs += res["outputs"]; messages.append(res["message"]); folder = res.get("folder") or folder
            else:
                for k, f in enumerate(files):
                    self._set(done=k, msg=f"Procesando {Path(f).name}")
                    try:
                        res = fn(f, out_dir=out_dir, progress=self._cb, **options)
                        outputs += res["outputs"]
                        if res["message"]:
                            messages.append(res["message"])
                        if res.get("folder") and len(files) == 1:
                            folder = res["folder"]
                    except core.ToolError as e:
                        errors.append(str(e))
                    except Exception as e:  # error inesperado en un archivo: seguir con los demás
                        traceback.print_exc()
                        errors.append(f"«{Path(f).name}»: error inesperado ({e}).")
        except core.ToolError as e:
            errors.append(str(e))
        except Exception as e:
            traceback.print_exc()
            errors.append(f"Error inesperado: {e}")
        finally:
            self._set(running=False, done=self._prog["total"])
        if not folder and outputs:
            folder = str(Path(outputs[0]).parent)
        return {"ok": bool(outputs), "outputs": outputs, "messages": messages, "errors": errors,
                "folder": folder or str(out_dir)}

    # ───────────── abrir en Windows ─────────────
    def open_path(self, path):
        p = str(path)
        if not os.path.exists(p):
            return False
        try:
            if os.name == "nt":
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
            return True
        except Exception:
            return False

    def open_folder(self, path):
        p = Path(path)
        if p.is_file():
            if os.name == "nt":  # abre el Explorador con el archivo seleccionado
                try:
                    subprocess.Popen(["explorer", "/select,", str(p)])
                    return True
                except Exception:
                    pass
            p = p.parent
        return self.open_path(str(p))
