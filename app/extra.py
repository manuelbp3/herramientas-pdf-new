"""Herramientas añadidas en la versión 2: PDF a Excel, comparar, rellenar formularios y tachar datos.

Se registran en core.TOOLS al final de core.py.
"""
from __future__ import annotations

import difflib
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from pypdf import PdfReader, PdfWriter

from . import render
from .core import (Progress, ToolError, _check_exists, _font, _noop, _reader, _res, _stem, page_count,
                   pdf_is_encrypted, unique_path)


def _plumber(path):
    try:
        import pdfplumber
    except Exception:
        raise ToolError("Falta el componente para leer tablas y texto (pdfplumber).")
    if pdf_is_encrypted(path):
        raise ToolError("El PDF está protegido con contraseña. Quita la protección primero.")
    try:
        return pdfplumber.open(str(_check_exists(path)))
    except Exception as e:
        raise ToolError(f"No se pudo abrir «{Path(path).name}»: {e}")


# ───────────────────────────── PDF a Excel ─────────────────────────────

_NUM_ES = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$|^-?\d+,\d+$")
_NUM_PLAIN = re.compile(r"^-?\d+(\.\d+)?$")


def _cell(v):
    """Texto de una celda → número si lo parece (acepta 1.234,56 y 12,5)."""
    s = ("" if v is None else str(v)).replace("\n", " ").strip()
    if not s:
        return ""
    if _NUM_ES.match(s):
        try:
            return float(s.replace(".", "").replace(",", "."))
        except ValueError:
            return s
    if _NUM_PLAIN.match(s) and not (len(s) > 1 and s[0] == "0" and "." not in s):  # no tocar códigos como 0045
        try:
            return int(s) if "." not in s else float(s)
        except ValueError:
            return s
    return s


def pdf_to_excel(file, out_dir, layout="sheets", borderless=False, progress: Progress = _noop, **_):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception:
        raise ToolError("Falta el componente para crear archivos de Excel (openpyxl).")
    settings = {"vertical_strategy": "text", "horizontal_strategy": "text"} if borderless else {}
    tables = []
    with _plumber(file) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            progress(i, n, f"Buscando tablas en la página {i + 1} de {n}")
            try:
                found = page.find_tables(settings) if settings else page.find_tables()
            except Exception:
                continue
            k = 0
            for t in found:
                rows = [[_cell(c) for c in row] for row in (t.extract() or [])]
                rows = [r for r in rows if any(str(c).strip() for c in r)]
                if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
                    continue
                k += 1
                tables.append((i + 1, k, rows))
    if not tables:
        hint = "" if borderless else " Prueba a activar «Tablas sin líneas»."
        raise ToolError(f"No he encontrado tablas en «{Path(file).name}».{hint} Si es un escaneo, usa antes la herramienta OCR.")
    wb = Workbook()
    wb.remove(wb.active)
    head_font, head_fill = Font(bold=True), PatternFill("solid", fgColor="E8EAF0")

    def write(ws, rows, r0, header=True):
        for ri, row in enumerate(rows):
            for ci, v in enumerate(row):
                c = ws.cell(row=r0 + ri, column=ci + 1, value=v)
                c.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(v) > 40)
                if header and ri == 0:
                    c.font, c.fill = head_font, head_fill
        return r0 + len(rows)

    if layout == "one":
        ws = wb.create_sheet("Tablas")
        r = 1
        for pg, k, rows in tables:
            ws.cell(row=r, column=1, value=f"Página {pg} · Tabla {k}").font = Font(bold=True, color="C0392B")
            r = write(ws, rows, r + 1) + 1
        sheets = [ws]
    else:
        sheets = []
        for pg, k, rows in tables:
            ws = wb.create_sheet(f"P{pg}-T{k}")
            write(ws, rows, 1)
            ws.freeze_panes = "A2"
            sheets.append(ws)
    for ws in sheets:
        for col in ws.columns:
            w = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(w + 2, 8), 60)
    out = unique_path(Path(out_dir) / f"{_stem(file)}.xlsx")
    wb.save(out)
    return _res([out], f"{len(tables)} tabla(s) guardadas en Excel. Revisa los datos: la lectura de tablas no siempre es perfecta.")


# ───────────────────────────── comparar dos PDF ─────────────────────────────

W_CMP = 1000


def _ink(img: Image.Image, size) -> "Image.Image":
    g = img.convert("L")
    if g.size != size:
        g = g.resize(size, Image.LANCZOS)
    return g.point(lambda v: 255 if v < 170 else 0)          # 255 = tinta


def _lines(reader, i):
    try:
        t = reader.pages[i].extract_text() or ""
    except Exception:
        return []
    return [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines() if ln.strip()]


def compare(files, out_dir, progress: Progress = _noop, **_):
    import numpy as np
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    if len(files) != 2:
        raise ToolError("Elige exactamente dos PDF: primero el original y después el modificado.")
    a, b = str(files[0]), str(files[1])
    ra, rb = _reader(a), _reader(b)
    na, nb = len(ra.pages), len(rb.pages)
    total = max(na, nb)
    pages, stats = [], []
    for i in range(total):
        progress(i, total, f"Comparando página {i + 1} de {total}")
        ia = render.render_width(a, i, W_CMP).convert("RGB") if i < na else None
        ib = render.render_width(b, i, W_CMP).convert("RGB") if i < nb else None
        ref = ia or ib
        size = ref.size
        ka = np.array(_ink(ia, size)) > 0 if ia else np.zeros(size[::-1], bool)
        kb = np.array(_ink(ib, size)) > 0 if ib else np.zeros(size[::-1], bool)
        def dil(m, r):
            """Engrosa una máscara r píxeles en cada dirección."""
            if not m.any():
                return m
            return np.array(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.BoxBlur(r))) > 0

        # un píxel de tinta cuenta como cambiado solo si no hay tinta del otro lado a ±1 px
        removed = ka & ~dil(kb, 1)
        added = kb & ~dil(ka, 1)
        out = np.full(size[::-1] + (3,), 255, np.uint8)
        out[ka | kb] = (150, 150, 150)
        # zonas cambiadas: un fondo suave alrededor para que se vea de un vistazo
        out[dil(removed, 12)] = (250, 200, 200)
        out[dil(added, 12)] = (190, 238, 208)
        out[ka | kb] = (150, 150, 150)
        out[dil(removed, 1)] = (225, 45, 45)
        out[dil(added, 1)] = (30, 160, 85)
        ink_total = int((ka | kb).sum()) or 1
        pct = (int(removed.sum()) + int(added.sum())) * 100.0 / ink_total
        la, lb = (_lines(ra, i) if i < na else []), (_lines(rb, i) if i < nb else [])
        sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
        rem_l, add_l = [], []
        for op, a0, a1, b0, b1 in sm.get_opcodes():
            if op in ("replace", "delete"):
                rem_l += la[a0:a1]
            if op in ("replace", "insert"):
                add_l += lb[b0:b1]
        status = "solo en el original" if ib is None else "solo en el modificado" if ia is None else ("igual" if pct < 0.15 and not rem_l and not add_l else "cambios")
        stats.append({"page": i + 1, "pct": pct, "rem": rem_l, "add": add_l, "status": status})
        pages.append(Image.fromarray(out))

    changed = [s for s in stats if s["status"] != "igual"]
    # informe: hoja de resumen + una página por cada página comparada
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    font = _font()
    Wp, Hp = A4
    y = Hp - 60

    def line(txt, size=11, color=(0.1, 0.1, 0.1), gap=16, x=50):
        nonlocal y
        if y < 60:
            c.showPage()
            y = Hp - 60
        c.setFont(font, size)
        c.setFillColorRGB(*color)
        c.drawString(x, y, txt[:110])
        y -= gap

    line("Comparación de documentos", 20, gap=28)
    line(f"Original (A): {Path(a).name} · {na} páginas", 11)
    line(f"Modificado (B): {Path(b).name} · {nb} páginas", 11, gap=22)
    c.setFillColorRGB(0.88, 0.18, 0.18); c.rect(50, y - 2, 10, 10, fill=1, stroke=0)
    line("Rojo: estaba en el original y ya no está", 10, x=66, gap=14)
    c.setFillColorRGB(0.12, 0.63, 0.33); c.rect(50, y - 2, 10, 10, fill=1, stroke=0)
    line("Verde: es nuevo en el modificado", 10, x=66, gap=14)
    c.setFillColorRGB(0.6, 0.6, 0.6); c.rect(50, y - 2, 10, 10, fill=1, stroke=0)
    line("Gris: no ha cambiado", 10, x=66, gap=24)
    if not changed:
        line("No se han detectado diferencias.", 13, (0.1, 0.5, 0.3), gap=22)
    else:
        line(f"Páginas con diferencias: {len(changed)} de {total}", 13, gap=22)
        for s in changed:
            lbl = {"cambios": f"{s['pct']:.1f} % de lo escrito ha cambiado", "solo en el original": "página solo en el original", "solo en el modificado": "página solo en el modificado"}[s["status"]]
            line(f"Página {s['page']}: {lbl}", 11, gap=15)
            for t in s["rem"][:4]:
                line("− " + t, 9.5, (0.75, 0.15, 0.15), 12, x=66)
            for t in s["add"][:4]:
                line("+ " + t, 9.5, (0.1, 0.5, 0.25), 12, x=66)
            extra = max(0, len(s["rem"]) - 4) + max(0, len(s["add"]) - 4)
            if extra:
                line(f"… y {extra} línea(s) más", 9.5, (0.4, 0.4, 0.4), 12, x=66)
            y -= 6
    c.showPage()
    c.save()
    buf.seek(0)
    w = PdfWriter()
    for p in PdfReader(buf).pages:
        w.add_page(p)
    for im in pages:
        pb = io.BytesIO()
        res = im.width / (595.0 if im.width <= im.height else 842.0) * 72
        im.save(pb, "PDF", resolution=res)
        pb.seek(0)
        w.add_page(PdfReader(pb).pages[0])
    out = unique_path(Path(out_dir) / f"Comparacion_{_stem(a)}_vs_{_stem(b)}.pdf")
    with open(out, "wb") as f:
        w.write(f)
    msg = "No se han detectado diferencias." if not changed else f"Diferencias en {len(changed)} de {total} páginas. La primera hoja es un resumen."
    return _res([out], msg)


# ───────────────────────────── formularios ─────────────────────────────

def form_fields(path) -> list[dict]:
    """Campos rellenables de un PDF: [{name, kind: text|check|choice, value, options, on}]"""
    r = _reader(path)
    out = []
    for name, f in (r.get_fields() or {}).items():
        ft = str(f.get("/FT", ""))
        flags = int(f.get("/Ff", 0) or 0)
        val = f.get("/V")
        val = "" if val is None else str(val)
        if ft == "/Tx":
            out.append({"name": name, "kind": "text", "value": val, "multiline": bool(flags & 4096)})
        elif ft == "/Btn":
            if flags & 65536:        # botón de acción
                continue
            states = [str(s) for s in (f.get("/_States_") or [])]
            on = next((s for s in states if s != "/Off"), "/Yes")
            if flags & 32768:        # opciones excluyentes
                out.append({"name": name, "kind": "choice", "radio": True, "value": val.lstrip("/"), "options": [s.lstrip("/") for s in states if s != "/Off"]})
            else:
                out.append({"name": name, "kind": "check", "value": val not in ("", "/Off"), "on": on})
        elif ft == "/Ch":
            opts = []
            for o in (f.get("/Opt") or []):
                opts.append(str(o[-1]) if isinstance(o, (list, tuple)) or o.__class__.__name__ == "ArrayObject" else str(o))
            out.append({"name": name, "kind": "choice", "value": val, "options": opts})
    return out


def fill_form(file, out_dir, values=None, flatten=False, progress: Progress = _noop, **_):
    import pikepdf

    values = values or {}
    r = _reader(file)
    fields = {f["name"]: f for f in form_fields(file)}
    if not fields:
        raise ToolError("Este PDF no tiene campos rellenables. Para escribir encima de cualquier PDF usa «Firmar y editar».")
    w = PdfWriter(clone_from=r)
    data = {}
    for name, v in values.items():
        f = fields.get(name)
        if not f:
            continue
        if f["kind"] == "check":
            data[name] = f["on"] if v in (True, "true", "True", 1, "1", "on") else "/Off"
        elif f.get("radio"):
            data[name] = "/" + str(v).lstrip("/") if v else "/Off"
        else:
            data[name] = str(v)
    for page in w.pages:
        try:
            w.update_page_form_field_values(page, data, auto_regenerate=False)
        except Exception:
            w.update_page_form_field_values(page, data)
    try:
        w.set_need_appearances_writer(True)
    except Exception:
        pass
    out = unique_path(Path(out_dir) / f"{_stem(file)}_rellenado.pdf")
    with open(out, "wb") as fh:
        w.write(fh)
    if flatten:
        try:
            with pikepdf.open(str(out), allow_overwriting_input=True) as pdf:
                pdf.generate_appearance_streams()
                pdf.flatten_annotations("screen")
                if "/AcroForm" in pdf.Root:
                    del pdf.Root["/AcroForm"]
                pdf.save(str(out))
        except Exception as e:
            raise ToolError(f"Se rellenó el formulario, pero no se pudo dejar fijo: {e}")
    n = sum(1 for v in data.values() if v not in ("", "/Off"))
    return _res([out], f"Formulario rellenado ({n} campo(s))." + (" Los campos ya no se pueden editar." if flatten else ""))


# ───────────────────────────── tachar datos sensibles ─────────────────────────────

PATTERNS = {
    "dni": ("DNI / NIE", r"(?<![A-Za-z0-9])(?:\d{8}[ -]?[A-Za-z]|[XYZxyz][ -]?\d{7}[ -]?[A-Za-z])(?![A-Za-z0-9])"),
    "iban": ("IBAN / cuenta", r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"),
    "email": ("Correo electrónico", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "phone": ("Teléfono", r"(?<!\d)(?:\+34[ .-]?)?[6-9]\d{2}(?:[ .-]?\d{3}[ .-]?\d{3}|[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2})(?!\d)"),
    "card": ("Tarjeta bancaria", r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"),
}
DPI_REDACT = 200


def _boxes_of(match) -> list[tuple[float, float, float, float]]:
    """Cajas (una por línea) de una coincidencia de pdfplumber."""
    lines: dict[int, list] = {}
    for ch in match.get("chars", []):
        lines.setdefault(round(ch["top"] / 3), []).append(ch)
    boxes = []
    for chars in lines.values():
        boxes.append((min(c["x0"] for c in chars), min(c["top"] for c in chars), max(c["x1"] for c in chars), max(c["bottom"] for c in chars)))
    return boxes


def redact(file, out_dir, kinds=None, words=None, progress: Progress = _noop, **_):
    kinds = [k for k in (kinds or []) if k in PATTERNS]
    words = [w.strip() for w in (words or []) if w and w.strip()]
    if not kinds and not words:
        raise ToolError("Marca qué datos quieres tachar o escribe alguna palabra.")
    if not render.available():
        raise ToolError("Falta el componente para dibujar páginas del PDF.")
    r = _reader(file)
    n = len(r.pages)
    found: dict[int, list] = {}
    counts: dict[str, int] = {}
    with _plumber(file) as pdf:
        if not any((p.chars for p in pdf.pages)):
            raise ToolError("Este PDF no tiene texto seleccionable (parece un escaneo), así que no puedo buscar datos en él. Usa antes la herramienta OCR.")
        for i, page in enumerate(pdf.pages):
            progress(i, n, f"Buscando en la página {i + 1} de {n}")
            rules = [(PATTERNS[k][0], PATTERNS[k][1]) for k in kinds] + [(f"«{w}»", re.escape(w)) for w in words]
            for label, rx in rules:
                try:
                    ms = page.search(rx, regex=True, case=False, return_chars=True)
                except Exception:
                    continue
                for m in ms:
                    found.setdefault(i, []).extend(_boxes_of(m))
                    counts[label] = counts.get(label, 0) + 1
    if not found:
        raise ToolError("No he encontrado nada que tachar con esas opciones.")
    w = PdfWriter()
    z = DPI_REDACT / 72.0
    for i, page in enumerate(r.pages):
        if i not in found:
            w.add_page(page)
            continue
        progress(i, n, f"Tachando la página {i + 1} de {n}")
        im = render.render_dpi(str(file), i, DPI_REDACT).convert("RGB")
        d = ImageDraw.Draw(im)
        # pdfplumber ya entrega las coordenadas con la página girada (tal como se ve),
        # igual que la imagen renderizada, así que no hace falta convertirlas.
        for x0, t, x1, b in found[i]:
            pad = 1.5
            d.rectangle([(x0 - pad) * z, (t - pad) * z, (x1 + pad) * z, (b + pad) * z], fill=(0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, "PDF", resolution=DPI_REDACT)
        buf.seek(0)
        w.add_page(PdfReader(buf).pages[0])
    w.add_metadata({"/Producer": "Herramientas PDF"})
    out = unique_path(Path(out_dir) / f"{_stem(file)}_tachado.pdf")
    with open(out, "wb") as fh:
        w.write(fh)
    resumen = ", ".join(f"{k}: {v}" for k, v in counts.items())
    return _res([out], f"Se han tachado {sum(counts.values())} dato(s) en {len(found)} página(s) ({resumen}). "
                       "Esas páginas se han convertido en imagen para que lo tapado no se pueda recuperar. Revisa el resultado.")


TOOLS = {"pdf2xlsx": pdf_to_excel, "compare": compare, "fillform": fill_form, "redact": redact}
