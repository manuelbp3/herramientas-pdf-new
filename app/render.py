"""Dibujar páginas de un PDF como imágenes (miniaturas, vista previa, OCR, PDF a JPG).

Usa PyMuPDF (fitz). Si no está disponible usa `pdftoppm` (poppler) como alternativa.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile

from PIL import Image

try:  # PyMuPDF
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None


def available() -> bool:
    return fitz is not None or shutil.which("pdftoppm") is not None


def _poppler(path: str, index: int, args: list[str]) -> Image.Image:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "p")
        subprocess.run(["pdftoppm", "-f", str(index + 1), "-l", str(index + 1), "-png", *args, path, out],
                       check=True, capture_output=True)
        files = sorted(glob.glob(out + "*.png"))
        if not files:
            raise RuntimeError("No se pudo dibujar la página.")
        return Image.open(files[0]).convert("RGB").copy()


def _fitz_page(doc, index: int):
    if doc.needs_pass:
        raise RuntimeError("El PDF está protegido con contraseña.")
    if index < 0 or index >= len(doc):
        raise RuntimeError("La página no existe.")
    return doc[index]


def render_dpi(path: str, index: int, dpi: int = 150) -> Image.Image:
    """Página `index` (desde 0) a una resolución dada en puntos por pulgada."""
    if fitz is not None:
        with fitz.open(path) as doc:
            page = _fitz_page(doc, index)
            z = dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return _poppler(path, index, ["-r", str(dpi)])


def render_width(path: str, index: int, width: int) -> Image.Image:
    """Página `index` (desde 0) con un ancho en píxeles."""
    if fitz is not None:
        with fitz.open(path) as doc:
            page = _fitz_page(doc, index)
            z = width / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return _poppler(path, index, ["-scale-to-x", str(width), "-scale-to-y", "-1"])


def render_many_width(path: str, start: int, count: int, width: int) -> list[Image.Image]:
    out: list[Image.Image] = []
    if fitz is not None:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise RuntimeError("El PDF está protegido con contraseña.")
            end = min(len(doc), start + count)
            for i in range(start, end):
                page = doc[i]
                z = width / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return out
    from pypdf import PdfReader
    total = len(PdfReader(path).pages)
    for i in range(start, min(total, start + count)):
        out.append(render_width(path, i, width))
    return out
