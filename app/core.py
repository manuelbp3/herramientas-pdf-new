"""Herramientas PDF: toda la lógica, sin interfaz.

Cada herramienta devuelve un diccionario:
    {"outputs": [rutas], "message": "texto", "folder": ruta o None}
y lanza ToolError con un mensaje claro cuando algo no se puede hacer.
"""
from __future__ import annotations

import base64
import datetime
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Callable

import pikepdf
from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageOps

from . import render

try:  # fotos HEIC del iPhone
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_OK = True
except Exception:  # pragma: no cover
    HEIC_OK = False

Progress = Callable[[int, int, str], None]


def _noop(done: int = 0, total: int = 0, msg: str = "") -> None:
    pass


class ToolError(Exception):
    """Error con un mensaje pensado para mostrarse a la persona."""


# ───────────────────────────── utilidades ─────────────────────────────

def downloads_dir() -> Path:
    if os.name == "nt":
        try:  # carpeta Descargas real (aunque esté redirigida a OneDrive u otra unidad)
            import ctypes
            from ctypes import wintypes

            guid = ctypes.c_char_p(b"\x90\xe2\x4d\x37\x3f\x12\x65\x45\x91\x64\x39\xc4\x92\x5e\x46\x7b")
            buf = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(buf))  # type: ignore[attr-defined]
            if res == 0 and buf.value:
                p = Path(buf.value)
                p.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass
    home = Path.home()
    for name in ("Downloads", "Descargas"):
        p = home / name
        if p.exists():
            return p
    p = home / "Downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "HerramientasPDF"
    p.mkdir(parents=True, exist_ok=True)
    return p


def unique_path(p: Path) -> Path:
    p = Path(p)
    if not p.exists():
        return p
    i = 1
    while True:
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
        i += 1


def ext_of(path) -> str:
    e = Path(path).suffix.lower().lstrip(".")
    return {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}.get(e, e)


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ","))
        n /= 1024
    return str(n)


def _res(outputs, message: str, folder=None) -> dict:
    return {"outputs": [str(o) for o in outputs], "message": message, "folder": str(folder) if folder else None}


def _check_exists(path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"No encuentro el archivo: {p.name}")
    return p


def _reader(path) -> PdfReader:
    p = _check_exists(path)
    try:
        r = PdfReader(str(p))
    except Exception as e:
        raise ToolError(f"No se pudo abrir «{p.name}»: {e}")
    if r.is_encrypted:
        try:
            ok = r.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise ToolError(f"«{p.name}» está protegido con contraseña. Quita la protección primero con la herramienta Desproteger.")
    return r


def page_count(path) -> int:
    return len(_reader(path).pages)


def pdf_is_encrypted(path) -> bool:
    try:
        r = PdfReader(str(path))
        if not r.is_encrypted:
            return False
        try:
            return not r.decrypt("")
        except Exception:
            return True
    except Exception:
        return False


def _save_writer(w: PdfWriter, out: Path) -> Path:
    out = unique_path(out)
    with open(out, "wb") as fh:
        w.write(fh)
    return out


def _stem(path) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", Path(path).stem)


def parse_ranges(text: str, n: int) -> list[tuple[str, list[int]]]:
    """«1-3, 5, 8-» -> [("1-3",[0,1,2]), ("5",[4]), ("8-",[7,...])]"""
    groups: list[tuple[str, list[int]]] = []
    for part in re.split(r"[;,]", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else n
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ToolError(f"Rango no válido: «{part}». Usa por ejemplo 1-3, 5, 8-")
        if a < 1 or b > n:
            raise ToolError(f"El rango «{part}» se sale del documento (tiene {n} páginas).")
        if a > b:
            raise ToolError(f"El rango «{part}» está al revés (escribe primero la página menor).")
        groups.append((f"{a}-{b}" if a != b else str(a), list(range(a - 1, b))))
    if not groups:
        raise ToolError("Escribe al menos un rango, por ejemplo 1-3, 5.")
    return groups


# ───────────────────────────── organizar ─────────────────────────────

def merge(files, out_dir, progress: Progress = _noop, **_):
    if len(files) < 2:
        raise ToolError("Elige al menos dos PDF para unirlos.")
    w = PdfWriter()
    for i, f in enumerate(files):
        progress(i, len(files), Path(f).name)
        w.append(_reader(f))
    out = _save_writer(w, Path(out_dir) / "unido.pdf")
    return _res([out], f"{len(files)} PDF unidos en uno solo")


def split(file, out_dir, mode="ranges", value="", n=2, progress: Progress = _noop, **_):
    r = _reader(file)
    total = len(r.pages)
    stem = _stem(file)
    out_dir = Path(out_dir)

    if mode == "extract":
        groups = parse_ranges(value, total)
        idxs = [i for _, idxs in groups for i in idxs]
        w = PdfWriter()
        for i in idxs:
            w.add_page(r.pages[i])
        out = _save_writer(w, out_dir / f"{stem}_extraido.pdf")
        return _res([out], f"{len(idxs)} páginas extraídas")

    if mode == "ranges":
        groups = parse_ranges(value, total)
    elif mode == "every":
        n = max(1, int(float(n)))
        groups = []
        for s in range(0, total, n):
            e = min(total, s + n)
            groups.append((f"{s + 1}-{e}" if e - s > 1 else str(s + 1), list(range(s, e))))
    elif mode == "all":
        groups = [(str(i + 1), [i]) for i in range(total)]
    else:
        raise ToolError("Elige cómo quieres dividir el PDF.")

    folder = unique_path(out_dir / f"{stem}_dividido")
    folder.mkdir(parents=True, exist_ok=True)
    outs = []
    for k, (label, idxs) in enumerate(groups):
        progress(k, len(groups), f"Parte {k + 1}")
        w = PdfWriter()
        for i in idxs:
            w.add_page(r.pages[i])
        outs.append(_save_writer(w, folder / f"{stem}_{label}.pdf"))
    return _res(outs, f"PDF dividido en {len(outs)} archivos", folder)


def organize(file, out_dir, pages=None, suffix="organizado", progress: Progress = _noop, **_):
    """pages: lista ordenada de {"i": índice desde 0, "rot": grados a girar}. Las páginas que no estén se eliminan."""
    r = _reader(file)
    total = len(r.pages)
    pages = pages or []
    if not pages:
        raise ToolError("El documento resultante no tendría ninguna página.")
    w = PdfWriter()
    for k, p in enumerate(pages):
        i = int(p["i"])
        if i < 0 or i >= total:
            raise ToolError("Hay una página que no existe en el documento.")
        page = r.pages[i]
        rot = int(p.get("rot", 0)) % 360
        if rot:
            page.rotate(rot)
        w.add_page(page)
    out = _save_writer(w, Path(out_dir) / f"{_stem(file)}_{suffix}.pdf")
    removed = total - len({int(p['i']) for p in pages})
    msg = f"PDF guardado con {len(pages)} páginas"
    if removed > 0:
        msg += f" ({removed} eliminadas)"
    return _res([out], msg)


def rotate(file, out_dir, degrees=90, **_):
    r = _reader(file)
    pages = [{"i": i, "rot": int(degrees)} for i in range(len(r.pages))]
    return organize(file, out_dir, pages=pages, suffix="girado")


# ───────────────────────────── optimizar ─────────────────────────────

_LEVELS = {"low": (85, 3000), "medium": (70, 2000), "high": (50, 1400)}


def compress(file, out_dir, level="medium", progress: Progress = _noop, **_):
    src = _check_exists(file)
    quality, maxdim = _LEVELS.get(level, _LEVELS["medium"])
    try:
        pdf = pikepdf.open(str(src))
    except pikepdf.PasswordError:
        raise ToolError(f"«{src.name}» está protegido con contraseña.")
    except Exception as e:
        raise ToolError(f"No se pudo abrir «{src.name}»: {e}")
    changed = 0
    with pdf:
        objs = [o for o in pdf.objects if isinstance(o, pikepdf.Stream)]
        for k, obj in enumerate(objs):
            try:
                if obj.get("/Subtype") != "/Image" or obj.get("/ImageMask", False) or "/Decode" in obj:
                    continue
                pim = pikepdf.PdfImage(obj)
                if pim.width < 300 and pim.height < 300:
                    continue
                im = pim.as_pil_image()
                if im.mode not in ("RGB", "L"):
                    continue
                if max(im.size) > maxdim:
                    im.thumbnail((maxdim, maxdim), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
                if len(data) >= len(obj.read_raw_bytes()) * 0.95:
                    continue
                obj.write(data, filter=pikepdf.Name.DCTDecode)
                obj.Width, obj.Height = im.size
                obj.ColorSpace = pikepdf.Name.DeviceRGB if im.mode == "RGB" else pikepdf.Name.DeviceGray
                obj.BitsPerComponent = 8
                if "/DecodeParms" in obj:
                    del obj["/DecodeParms"]
                changed += 1
            except Exception:
                continue
            if k % 20 == 0:
                progress(k, len(objs), "Optimizando imágenes")
        tmp = unique_path(Path(out_dir) / f"{_stem(src)}_comprimido.pdf")
        pdf.save(str(tmp), compress_streams=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate, recompress_flate=True)
    before, after = src.stat().st_size, tmp.stat().st_size
    if after >= before:
        tmp.unlink(missing_ok=True)
        return _res([], f"«{src.name}» ya estaba optimizado ({fmt_size(before)}); no se puede reducir más con este nivel.")
    pct = round((1 - after / before) * 100)
    return _res([tmp], f"{src.name}: de {fmt_size(before)} a {fmt_size(after)} (−{pct} %)")


def repair(file, out_dir, **_):
    src = _check_exists(file)
    try:
        with pikepdf.open(str(src)) as pdf:
            out = unique_path(Path(out_dir) / f"{_stem(src)}_reparado.pdf")
            pdf.save(str(out))
    except pikepdf.PasswordError:
        raise ToolError(f"«{src.name}» está protegido con contraseña.")
    except Exception as e:
        raise ToolError(f"No se pudo reparar «{src.name}»: {e}")
    return _res([out], f"{src.name} reparado y guardado de nuevo")


# ─────────────────────── dibujar encima de las páginas ───────────────────────

_FONT: str | None = None


def _font() -> str:
    """Fuente con soporte de acentos y símbolos (Arial en Windows)."""
    global _FONT
    if _FONT:
        return _FONT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    cands = [r"C:\Windows\Fonts\arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for c in cands:
        if os.path.exists(c):
            try:
                pdfmetrics.registerFont(TTFont("UFont", c))
                _FONT = "UFont"
                return _FONT
            except Exception:
                continue
    _FONT = "Helvetica"
    return _FONT


def _make_overlay(page, draw):
    """Crea una página transparente con lo que dibuje `draw(canvas, ancho_visible, alto_visible)`.
    Las coordenadas son las de la página tal como se ve (origen abajo a la izquierda), aunque esté girada."""
    from reportlab.pdfgen import canvas

    box = page.mediabox
    x0, y0, W, H = float(box.left), float(box.bottom), float(box.width), float(box.height)
    rot = (page.rotation or 0) % 360
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(x0 + W, y0 + H))
    c.translate(x0, y0)
    if rot == 90:
        c.transform(0, 1, -1, 0, W, 0)
        vw, vh = H, W
    elif rot == 180:
        c.transform(-1, 0, 0, -1, W, H)
        vw, vh = W, H
    elif rot == 270:
        c.transform(0, -1, 1, 0, 0, H)
        vw, vh = H, W
    else:
        vw, vh = W, H
    draw(c, vw, vh)
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _hex(color: str):
    from reportlab.lib import colors

    try:
        return colors.HexColor(color or "#000000")
    except Exception:
        return colors.black


def _process_pages(file, out_dir, suffix, make_draw, progress: Progress = _noop):
    r = _reader(file)
    w = PdfWriter()
    n = len(r.pages)
    for i, page in enumerate(r.pages):
        if i % 10 == 0:
            progress(i, n, f"Página {i + 1} de {n}")
        draw = make_draw(i, n)
        overlay = _make_overlay(page, draw) if draw is not None else None
        wp = w.add_page(page)
        if overlay is not None:
            wp.merge_page(overlay)
    return _save_writer(w, Path(out_dir) / f"{_stem(file)}_{suffix}.pdf")


def watermark(file, out_dir, text="CONFIDENCIAL", size=60, opacity=0.25, angle=45, color="#888888",
              position="center", progress: Progress = _noop, **_):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    text = (text or "").strip()
    if not text:
        raise ToolError("Escribe el texto de la marca de agua.")
    size, opacity, angle = float(size), max(0.02, min(1.0, float(opacity))), float(angle)
    font = _font()
    col = _hex(color)

    def make_draw(i, n):
        def draw(c, vw, vh):
            s = size
            avail = (math.hypot(vw, vh) * 0.8) if (position == "center" and abs(angle) > 1) else vw * 0.9
            tw = stringWidth(text, font, s)
            if tw > avail:
                s = s * avail / tw
            c.saveState()
            c.setFillColor(col)
            c.setFillAlpha(opacity)
            c.setFont(font, s)
            if position == "top":
                c.drawCentredString(vw / 2, vh - 30 - s, text)
            elif position == "bottom":
                c.drawCentredString(vw / 2, 30, text)
            else:
                c.translate(vw / 2, vh / 2)
                c.rotate(angle)
                c.drawCentredString(0, -s * 0.35, text)
            c.restoreState()
        return draw

    out = _process_pages(file, out_dir, "marca", make_draw, progress)
    return _res([out], "Marca de agua añadida a todas las páginas")


def page_numbers(file, out_dir, position="bottom-center", fmt="{n}", start=1, size=11, margin=12,
                 skip_first=False, progress: Progress = _noop, **_):
    font = _font()
    size, margin, start = float(size), float(margin) * 72 / 25.4, int(float(start))
    fmt = fmt or "{n}"
    first = 1 if skip_first else 0

    def make_draw(i, n):
        if i < first:
            return None
        label = fmt.replace("{n}", str(start + i - first)).replace("{total}", str(n))

        def draw(c, vw, vh):
            c.setFont(font, size)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            vert, horiz = position.split("-")
            y = margin if vert == "bottom" else vh - margin - size * 0.8
            if horiz == "left":
                c.drawString(margin, y, label)
            elif horiz == "right":
                c.drawRightString(vw - margin, y, label)
            else:
                c.drawCentredString(vw / 2, y, label)
        return draw

    out = _process_pages(file, out_dir, "numerado", make_draw, progress)
    return _res([out], "Números de página añadidos")


def crop(file, out_dir, left=0, top=0, right=0, bottom=0, **_):
    """Márgenes a quitar, en milímetros, tal como se ve la página."""
    k = 72 / 25.4
    l, t, r_, b = (max(0.0, float(v)) * k for v in (left, top, right, bottom))
    if l + t + r_ + b <= 0:
        raise ToolError("Indica cuánto quieres recortar en algún borde.")
    rd = _reader(file)
    w = PdfWriter()
    for page in rd.pages:
        rot = (page.rotation or 0) % 360
        # márgenes visibles -> márgenes de la página sin girar (izq, abajo, der, arriba)
        if rot == 90:
            ml, mb, mr, mt = t, l, b, r_
        elif rot == 180:
            ml, mb, mr, mt = r_, t, l, b
        elif rot == 270:
            ml, mb, mr, mt = b, r_, t, l
        else:
            ml, mb, mr, mt = l, b, r_, t
        box = page.mediabox
        x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
        nx0, ny0, nx1, ny1 = x0 + ml, y0 + mb, x1 - mr, y1 - mt
        if nx1 - nx0 < 20 or ny1 - ny0 < 20:
            raise ToolError("Los márgenes son demasiado grandes: no quedaría página.")
        for attr in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
            try:
                setattr(page, attr, type(box)([nx0, ny0, nx1, ny1]))
            except Exception:
                pass
        w.add_page(page)
    out = _save_writer(w, Path(out_dir) / f"{_stem(file)}_recortado.pdf")
    return _res([out], "PDF recortado")


def _draw_item(c, vw, vh, it):
    from reportlab.lib.utils import ImageReader

    x, y = float(it["x"]), float(it["y"])
    if it.get("type") == "text":
        text = str(it.get("text", ""))
        if not text.strip():
            return
        fs = float(it.get("fs", 0.03)) * vw
        c.saveState()
        c.setFillColor(_hex(it.get("color", "#000000")))
        c.setFont(_font(), fs)
        base = y * vh + fs * 0.9465
        for k, line in enumerate(text.split("\n")):
            c.drawString(x * vw, vh - (base + k * fs * 1.2), line)
        c.restoreState()
    else:
        path = it.get("image")
        if not path or not os.path.isfile(path):
            return
        reader = ImageReader(path)
        iw, ih = reader.getSize()
        wpt = float(it.get("w", 0.25)) * vw
        hpt = wpt * ih / iw
        c.drawImage(reader, x * vw, vh - y * vh - hpt, wpt, hpt, mask="auto")


def stamp(file, out_dir, items=None, progress: Progress = _noop, **_):
    """Coloca firmas, imágenes o textos. Cada elemento: {type, x, y, w|fs, pages:[índices], image|text, color}.
    x, y, w son fracciones del ancho/alto de la página (x, y = esquina superior izquierda)."""
    items = items or []
    if not items:
        raise ToolError("Añade al menos una firma, imagen o texto al documento.")
    r = _reader(file)
    n = len(r.pages)
    by_page: dict[int, list] = {}
    for it in items:
        for p in it.get("pages") or []:
            if 0 <= int(p) < n:
                by_page.setdefault(int(p), []).append(it)
    if not by_page:
        raise ToolError("Ninguno de los elementos está en una página del documento.")
    w = PdfWriter()
    for i, page in enumerate(r.pages):
        its = by_page.get(i)
        overlay = None
        if its:
            def draw(c, vw, vh, its=its):
                for it in its:
                    _draw_item(c, vw, vh, it)
            overlay = _make_overlay(page, draw)
        wp = w.add_page(page)
        if overlay is not None:
            wp.merge_page(overlay)
    out = _save_writer(w, Path(out_dir) / f"{_stem(file)}_firmado.pdf")
    return _res([out], f"{len(items)} elemento(s) añadidos al PDF")


# ───────────────────────────── seguridad ─────────────────────────────

def protect(file, out_dir, password="", **_):
    if not password:
        raise ToolError("Escribe la contraseña con la que quieres proteger el PDF.")
    src = _check_exists(file)
    try:
        with pikepdf.open(str(src)) as pdf:
            out = unique_path(Path(out_dir) / f"{_stem(src)}_protegido.pdf")
            pdf.save(str(out), encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    except pikepdf.PasswordError:
        raise ToolError(f"«{src.name}» ya tiene contraseña. Quítala primero con Desproteger.")
    except Exception as e:
        raise ToolError(f"No se pudo proteger «{src.name}»: {e}")
    return _res([out], f"{src.name} protegido con contraseña")


def unlock(file, out_dir, password="", **_):
    src = _check_exists(file)
    try:
        with pikepdf.open(str(src), password=password or "") as pdf:
            out = unique_path(Path(out_dir) / f"{_stem(src)}_desprotegido.pdf")
            pdf.save(str(out))
    except pikepdf.PasswordError:
        raise ToolError("La contraseña no es correcta." if password else f"«{src.name}» necesita su contraseña para abrirse.")
    except Exception as e:
        raise ToolError(f"No se pudo desproteger «{src.name}»: {e}")
    return _res([out], f"{src.name} sin contraseña")


# ───────────────────────────── OCR ─────────────────────────────

def tesseract_cmd() -> str | None:
    here = Path(__file__).resolve().parent
    roots = [here.parent / "tesseract", here.parent.parent / "tesseract", Path(sys.executable).parent / "tesseract"]
    for r in roots:
        for name in ("tesseract.exe", "tesseract"):
            p = r / name
            if p.is_file():
                os.environ.setdefault("TESSDATA_PREFIX", str(r / "tessdata"))
                return str(p)
    found = shutil.which("tesseract")
    if found:
        return found
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.isfile(p):
            return p
    return None


def ocr_available() -> bool:
    return tesseract_cmd() is not None and render.available()


def ocr_languages() -> list[str]:
    cmd = tesseract_cmd()
    if not cmd:
        return []
    try:
        out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=30).stdout
        return [l.strip() for l in out.splitlines()[1:] if l.strip() and l.strip() != "osd"]
    except Exception:
        return []


def ocr(file, out_dir, lang="spa+eng", output="pdf", dpi=300, progress: Progress = _noop, **_):
    import pytesseract
    from pypdf import PdfReader as _R

    cmd = tesseract_cmd()
    if not cmd:
        raise ToolError("El reconocimiento de texto (OCR) necesita Tesseract, que no está instalado en este equipo.")
    if not render.available():
        raise ToolError("Falta el componente para dibujar páginas del PDF.")
    pytesseract.pytesseract.tesseract_cmd = cmd
    have = set(ocr_languages())
    wanted = [l for l in (lang or "eng").split("+") if l in have] or (["eng"] if "eng" in have else list(have)[:1])
    if not wanted:
        raise ToolError("Tesseract no tiene ningún idioma instalado.")
    langs = "+".join(wanted)
    n = page_count(file)
    w = PdfWriter()
    for i in range(n):
        progress(i, n, f"Reconociendo texto: página {i + 1} de {n}")
        img = render.render_dpi(str(file), i, dpi).convert("L")
        data = pytesseract.image_to_pdf_or_hocr(img, lang=langs, extension="pdf", config=f"--dpi {dpi}")
        w.append(_R(io.BytesIO(data)))
    stem = _stem(file)
    outs = []
    if output in ("pdf", "both"):
        outs.append(_save_writer(w, Path(out_dir) / f"{stem}_ocr.pdf"))
    if output in ("txt", "both"):
        buf = io.BytesIO()
        w.write(buf)
        buf.seek(0)
        text = "\n\n".join((p.extract_text() or "") for p in _R(buf).pages)
        t = unique_path(Path(out_dir) / f"{stem}_ocr.txt")
        t.write_text(text, encoding="utf-8")
        outs.append(t)
    return _res(outs, f"Texto reconocido en {n} páginas (idioma: {langs})")


# ───────────────────────────── convertir desde PDF ─────────────────────────────

def pdf_to_images(file, out_dir, fmt="jpg", dpi=150, progress: Progress = _noop, **_):
    if not render.available():
        raise ToolError("Falta el componente para dibujar páginas del PDF.")
    if pdf_is_encrypted(file):
        raise ToolError("El PDF está protegido con contraseña. Quita la protección primero.")
    n = page_count(file)
    fmt = "png" if fmt == "png" else "jpg"
    stem = _stem(file)
    dpi = int(float(dpi))

    def save(img, path):
        if fmt == "jpg":
            img.convert("RGB").save(path, "JPEG", quality=90)
        else:
            img.save(path, "PNG")

    if n == 1:
        out = unique_path(Path(out_dir) / f"{stem}.{fmt}")
        save(render.render_dpi(str(file), 0, dpi), out)
        return _res([out], "Página convertida a imagen")
    folder = unique_path(Path(out_dir) / f"{stem}_imagenes")
    folder.mkdir(parents=True, exist_ok=True)
    outs = []
    for i in range(n):
        progress(i, n, f"Página {i + 1} de {n}")
        p = folder / f"{stem}_pagina_{i + 1}.{fmt}"
        save(render.render_dpi(str(file), i, dpi), p)
        outs.append(p)
    return _res(outs, f"{n} páginas guardadas como imágenes", folder)


def pdf_to_word(file, out_dir, progress: Progress = _noop, **_):
    if pdf_is_encrypted(file):
        raise ToolError("El PDF está protegido con contraseña. Quita la protección primero.")
    try:
        from pdf2docx import Converter
    except Exception:
        raise ToolError("Falta el componente para convertir a Word (pdf2docx).")
    out = unique_path(Path(out_dir) / f"{_stem(file)}.docx")
    cv = Converter(str(file))
    try:
        cv.convert(str(out))
    except Exception as e:
        raise ToolError(f"No se pudo convertir a Word: {e}")
    finally:
        cv.close()
    return _res([out], "Convertido a Word. Si el PDF era un escaneo, usa antes la herramienta OCR.")


def pdf_to_text(file, out_dir, **_):
    r = _reader(file)
    pages = [(p.extract_text() or "").strip() for p in r.pages]
    if not any(pages):
        raise ToolError("Este PDF no tiene texto seleccionable (parece un escaneo). Usa antes la herramienta OCR.")
    out = unique_path(Path(out_dir) / f"{_stem(file)}.txt")
    out.write_text("\n\n".join(pages), encoding="utf-8")
    return _res([out], "Texto extraído")


# ───────────────────────────── convertir a PDF / imágenes ─────────────────────────────

def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.exists(p):
            return p
    return None


def office_to_pdf(file, out_dir, **_):
    src = _check_exists(file)
    soffice = find_soffice()
    if not soffice:
        raise ToolError("Para convertir Word, Excel o PowerPoint a PDF necesitas instalar LibreOffice (gratis): libreoffice.org/download")
    with tempfile.TemporaryDirectory() as tmp:
        profile = (Path(tmp) / "perfil").as_uri()
        cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)]
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=300, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise ToolError(f"«{src.name}» tardó demasiado en convertirse.")
        except subprocess.CalledProcessError:
            raise ToolError(f"LibreOffice no pudo convertir «{src.name}».")
        res = list(Path(tmp).glob("*.pdf"))
        if not res:
            raise ToolError(f"No se pudo generar el PDF de «{src.name}».")
        out = unique_path(Path(out_dir) / f"{_stem(src)}.pdf")
        shutil.move(str(res[0]), out)
    return _res([out], f"{src.name} convertido a PDF")


def _flat_rgb(im: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def images_to_pdf(files, out_dir, page="a4", margin="small", progress: Progress = _noop, **_):
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.pdfgen import canvas

    if not files:
        raise ToolError("Elige al menos una imagen.")
    out = unique_path(Path(out_dir) / ("imagenes.pdf" if len(files) > 1 else f"{_stem(files[0])}.pdf"))
    mg = {"none": 0, "small": 28, "big": 57}.get(margin, 28)
    c = canvas.Canvas(str(out))
    with tempfile.TemporaryDirectory() as tmp:
        for k, f in enumerate(files):
            progress(k, len(files), Path(f).name)
            try:
                im = _flat_rgb(Image.open(_check_exists(f)))
            except ToolError:
                raise
            except Exception:
                raise ToolError(f"No se pudo abrir la imagen «{Path(f).name}».")
            iw, ih = im.size
            if page == "original":
                W, H = iw * 0.75, ih * 0.75
                m = 0
            else:
                base = letter if page == "letter" else A4
                W, H = (max(base), min(base)) if iw > ih else (min(base), max(base))
                m = mg
            c.setPageSize((W, H))
            s = min((W - 2 * m) / iw, (H - 2 * m) / ih)
            w, h = iw * s, ih * s
            tmpf = os.path.join(tmp, f"i{k}.jpg")
            im.save(tmpf, "JPEG", quality=92)
            c.drawImage(tmpf, (W - w) / 2, (H - h) / 2, w, h)
            c.showPage()
        c.save()
    return _res([out], f"{len(files)} imagen(es) convertidas a PDF")


def convert_image(file, out_dir, target="jpg", quality=92, **_):
    src = _check_exists(file)
    target = {"jpeg": "jpg"}.get(target, target)
    fmts = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF"}
    if target not in fmts:
        raise ToolError("Formato de destino no compatible.")
    if ext_of(src) == "heic" and not HEIC_OK:
        raise ToolError("Falta el componente para abrir fotos HEIC (pillow-heif).")
    try:
        im = ImageOps.exif_transpose(Image.open(src))
    except Exception:
        raise ToolError(f"No se pudo abrir «{src.name}».")
    if target in ("jpg", "bmp") and im.mode != "RGB":
        im = _flat_rgb(im)
    out = unique_path(Path(out_dir) / f"{_stem(src)}.{target}")
    kw = {"quality": int(float(quality))} if target in ("jpg", "webp") else {}
    im.save(out, fmts[target], **kw)
    return _res([out], f"{src.name} → {target.upper()}")


# ───────────────────────────── firmas guardadas ─────────────────────────────

def signatures_dir() -> Path:
    p = app_data_dir() / "firmas"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _trim(im: Image.Image) -> Image.Image | None:
    im = im.convert("RGBA")
    box = im.split()[-1].point(lambda v: 255 if v > 20 else 0).getbbox()
    if not box:
        return None
    pad = 6
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    return im.crop(box)


def save_signature_image(im: Image.Image) -> str:
    t = _trim(im)
    if t is None:
        raise ToolError("No se ve ninguna firma. Dibújala o usa una foto con tinta oscura sobre papel blanco.")
    if max(t.size) > 1000:
        t.thumbnail((1000, 1000), Image.LANCZOS)
    sid = uuid.uuid4().hex[:12]
    t.save(signatures_dir() / f"{sid}.png")
    return sid


def save_signature_dataurl(data_url: str) -> str:
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw))
    except Exception:
        raise ToolError("No se pudo leer la firma dibujada.")
    return save_signature_image(im)


def save_signature_from_file(path: str) -> str:
    try:
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except Exception:
        raise ToolError("No se pudo abrir esa imagen.")
    im.thumbnail((1400, 1400))
    g = im.convert("L")
    alpha = g.point(lambda v: 0 if v > 215 else (255 if v < 140 else int((215 - v) / 75 * 255)))
    ink = im.point(lambda v: int(v * 0.4))
    ink.putalpha(alpha)
    return save_signature_image(ink)


def list_signatures() -> list[str]:
    return [p.stem for p in sorted(signatures_dir().glob("*.png"), key=lambda p: p.stat().st_mtime)]


def signature_path(sid: str) -> str | None:
    if not re.fullmatch(r"[0-9a-f]{12}", sid or ""):
        return None
    p = signatures_dir() / f"{sid}.png"
    return str(p) if p.is_file() else None


def delete_signature(sid: str) -> None:
    p = signature_path(sid)
    if p:
        os.remove(p)


TOOLS = {
    "merge": merge, "split": split, "organize": organize, "rotate": rotate,
    "compress": compress, "repair": repair, "watermark": watermark, "numbers": page_numbers,
    "crop": crop, "edit": stamp, "protect": protect, "unlock": unlock, "ocr": ocr,
    "pdf2img": pdf_to_images, "pdf2word": pdf_to_word, "pdf2txt": pdf_to_text,
    "office2pdf": office_to_pdf, "img2pdf": images_to_pdf, "imgconv": convert_image,
}
COMBINE = {"merge", "img2pdf"}            # usan todos los archivos a la vez
SINGLE = {"split", "organize", "edit"}    # un solo archivo con opciones propias

# herramientas añadidas (PDF a Excel, comparar, formularios, tachar)
from . import extra as _extra  # noqa: E402

TOOLS.update(_extra.TOOLS)
COMBINE.add("compare")
SINGLE.add("fillform")
