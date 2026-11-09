"""Pruebas de las herramientas nuevas. Ejecutar:  python -m tests.test_extra"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from app import core, render, extra

T = Path(tempfile.mkdtemp(prefix="extratest_")); OUT = T / "out"; OUT.mkdir()
os.environ["APPDATA"] = str(T / "appdata")
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  OK  ", name, extra)
    else: fail += 1; print("  FALLA", name, extra)
def raises(fn):
    try: fn(); return False
    except core.ToolError as e: return str(e)

# ───── PDF a Excel ─────
print("PDF a Excel")
styles = getSampleStyleSheet()
data = [["Concepto", "Unidades", "Precio", "Total"], ["Tornillos", "100", "0,25", "25,00"], ["Tuercas", "50", "0,40", "20,00"], ["Arandelas", "1.200", "0,05", "60,00"], ["Código", "0045", "1.234,56", "7.000,50"]]
tp = T / "tabla.pdf"
SimpleDocTemplate(str(tp), pagesize=A4).build([Paragraph("Factura de ejemplo", styles["Title"]), Spacer(1, 12),
    Table(data, style=TableStyle([("GRID", (0, 0), (-1, -1), .6, colors.black)]))])
r = core.TOOLS["pdf2xlsx"](str(tp), OUT)
from openpyxl import load_workbook
ws = load_workbook(r["outputs"][0]).worksheets[0]
rows = [[c.value for c in row] for row in ws.iter_rows()]
check("hay 5 filas y 4 columnas", len(rows) == 5 and len(rows[0]) == 4, str(rows[:2]))
check("texto en cabecera", rows[0][0] == "Concepto")
check("100 → número entero", rows[1][1] == 100)
check("0,25 → 0.25", rows[1][2] == 0.25)
check("1.200 → 1200", rows[3][1] == 1200)
check("1.234,56 → 1234.56", abs(rows[4][2] - 1234.56) < 1e-9)
check("código 0045 se queda como texto", rows[4][1] == "0045")
r1 = core.TOOLS["pdf2xlsx"](str(tp), OUT, layout="one")
check("una sola hoja", len(load_workbook(r1["outputs"][0]).worksheets) == 1)
nt = T / "sintabla.pdf"; c = canvas.Canvas(str(nt)); c.drawString(72, 700, "Solo un parrafo de texto sin tablas."); c.save()
check("sin tablas → error claro", "No he encontrado tablas" in (raises(lambda: core.TOOLS["pdf2xlsx"](str(nt), OUT)) or ""))
bl = T / "sinlineas.pdf"; c = canvas.Canvas(str(bl)); c.setFont("Helvetica", 11)
for i, row in enumerate([["Nombre", "Edad", "Ciudad"], ["Ana", "31", "Madrid"], ["Luis", "45", "Sevilla"], ["Marta", "28", "Bilbao"]]):
    for j, v in enumerate(row): c.drawString(72 + j * 120, 700 - i * 22, v)
c.save()
r2 = core.TOOLS["pdf2xlsx"](str(bl), OUT, borderless=True)
w2 = [[c.value for c in row] for row in load_workbook(r2["outputs"][0]).worksheets[0].iter_rows()]
check("tabla sin líneas detectada", len(w2) >= 3 and w2[1][:1] == ["Ana"], str(w2[:2]))

# ───── Comparar ─────
print("Comparar")
def doc(path, lines_by_page):
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in lines_by_page:
        c.setFont("Helvetica", 14)
        for k, ln in enumerate(lines): c.drawString(72, 780 - k * 24, ln)
        c.showPage()
    c.save()
A, B = T / "v1.pdf", T / "v2.pdf"
base = ["Contrato de alquiler", "Precio mensual: 800 euros", "Duracion: 12 meses", "Fianza: dos mensualidades"]
doc(A, [base, ["Anexo uno", "Texto igual"]])
doc(B, [["Contrato de alquiler", "Precio mensual: 950 euros", "Duracion: 12 meses", "Fianza: dos mensualidades"], ["Anexo uno", "Texto igual"], ["Pagina nueva"]])
r = core.TOOLS["compare"]([str(A), str(B)], OUT)
rd = PdfReader(r["outputs"][0])
check("resumen + 3 páginas", len(rd.pages) == 4, str(len(rd.pages)))
txt = rd.pages[0].extract_text()
check("el resumen cita 800/950", "800" in txt and "950" in txt, txt.replace("\n", " | ")[:160])
check("el resumen dice 2 páginas con diferencias", "2 de 3" in txt, "")
im = np.array(render.render_dpi(r["outputs"][0], 1, 60).convert("RGB")).astype(int)
red = ((im[..., 0] - im[..., 1] > 25) & (im[..., 0] - im[..., 2] > 25)).sum(); green = ((im[..., 1] - im[..., 0] > 25) & (im[..., 1] - im[..., 2] > 5)).sum()
check("la página 1 tiene rojo y verde", red > 20 and green > 20, f"rojo={red} verde={green}")
im2 = np.array(render.render_dpi(r["outputs"][0], 2, 60).convert("RGB")).astype(int)
check("página 2 igual: sin rojo ni verde", ((im2[..., 0] - im2[..., 1] > 25) & (im2[..., 0] - im2[..., 2] > 25)).sum() < 5 and ((im2[..., 1] - im2[..., 0] > 25) & (im2[..., 1] - im2[..., 2] > 5)).sum() < 5)
r = core.TOOLS["compare"]([str(A), str(A)], OUT)
check("mismo archivo → sin diferencias", "No se han detectado" in r["message"], r["message"])
check("necesita dos archivos", bool(raises(lambda: core.TOOLS["compare"]([str(A)], OUT))))

# ───── Formularios ─────
print("Formularios")
fp = T / "form.pdf"; c = canvas.Canvas(str(fp), pagesize=A4); f = c.acroForm
c.setFont("Helvetica", 12); c.drawString(72, 790, "Solicitud")
f.textfield(name="nombre", x=72, y=740, width=250, height=22, borderStyle="inset", forceBorder=True)
f.textfield(name="notas", x=72, y=680, width=250, height=40, fieldFlags="multiline", forceBorder=True)
f.checkbox(name="acepto", x=72, y=640, size=18, checked=False, forceBorder=True)
f.choice(name="pais", x=72, y=600, width=150, height=22, options=["España", "Francia", "Italia"], value="España", forceBorder=True)
f.radio(name="sexo", value="H", x=72, y=560, size=16, selected=False); f.radio(name="sexo", value="M", x=110, y=560, size=16, selected=False)
c.save()
fl = core.TOOLS and extra.form_fields(str(fp))
names = {x["name"]: x for x in fl}
check("detecta 5 campos", len(fl) == 5, str([(x['name'], x['kind']) for x in fl]))
check("tipos correctos", names["nombre"]["kind"] == "text" and names["acepto"]["kind"] == "check" and names["pais"]["kind"] == "choice")
check("opciones del desplegable", names["pais"]["options"] == ["España", "Francia", "Italia"], str(names["pais"]["options"]))
r = core.TOOLS["fillform"](str(fp), OUT, values={"nombre": "Manuel García", "notas": "Primera línea", "acepto": True, "pais": "Francia", "sexo": "M"})
got = PdfReader(r["outputs"][0]).get_fields()
check("texto guardado", got["nombre"].get("/V") == "Manuel García", str(got["nombre"].get("/V")))
check("casilla marcada", str(got["acepto"].get("/V")) not in ("", "/Off", "None"), str(got["acepto"].get("/V")))
check("desplegable", str(got["pais"].get("/V")) == "Francia")
check("opción excluyente", str(got["sexo"].get("/V")) == "/M", str(got["sexo"].get("/V")))
# se ve al dibujar
a0 = np.array(render.render_dpi(str(fp), 0, 80).convert("L")).astype(int); a1 = np.array(render.render_dpi(r["outputs"][0], 0, 80).convert("L")).astype(int)
check("lo escrito se ve en la página", (abs(a0 - a1) > 60).sum() > 200, str((abs(a0 - a1) > 60).sum()))
rf = core.TOOLS["fillform"](str(fp), OUT, values={"nombre": "Fijo Ya"}, flatten=True)
check("aplanado: sin campos", not (PdfReader(rf["outputs"][0]).get_fields() or {}))
b0 = np.array(render.render_dpi(rf["outputs"][0], 0, 80).convert("L")).astype(int)
check("aplanado: el texto sigue visible", (abs(a0 - b0) > 60).sum() > 100, str((abs(a0 - b0) > 60).sum()))
check("PDF sin formulario → error claro", "no tiene campos" in (raises(lambda: core.TOOLS["fillform"](str(A), OUT, values={})) or ""))

# ───── Tachar ─────
print("Tachar")
sp = T / "datos.pdf"; c = canvas.Canvas(str(sp), pagesize=A4); c.setFont("Helvetica", 13)
rowsd = ["Cliente: Juan Perez  DNI 12345678Z", "NIE: X1234567L", "IBAN: ES91 2100 0418 4502 0005 1332", "Correo: juan.perez@ejemplo.com", "Telefono: 612 345 678", "Notas: informacion Confidencial del proyecto Azul"]
for k, t in enumerate(rowsd): c.drawString(72, 780 - k * 28, t)
c.showPage(); c.setFont("Helvetica", 13); c.drawString(72, 780, "Pagina dos sin datos personales."); c.showPage()
c.setFont("Helvetica", 13); c.drawString(72, 780, "Tercera pagina: telefono 699-11-22-33"); c.showPage(); c.save()
rr = PdfReader(str(sp)); wr = PdfWriter()
for i, p in enumerate(rr.pages):
    if i == 2: p.rotate(90)
    wr.add_page(p)
wr.write(str(sp))
r = core.TOOLS["redact"](str(sp), OUT, kinds=["dni", "iban", "email", "phone"], words=["Confidencial", "Azul"])
outp = PdfReader(r["outputs"][0])
t0 = outp.pages[0].extract_text() or ""
check("3 páginas", len(outp.pages) == 3)
for s in ("12345678Z", "X1234567L", "2100", "juan.perez", "612 345 678", "Confidencial"):
    check(f"«{s}» ya no se puede recuperar", s not in t0)
check("página 2 (sin datos) sigue con su texto", "sin datos personales" in (outp.pages[1].extract_text() or ""))
check("página 3 girada: teléfono tachado", "699" not in (outp.pages[2].extract_text() or ""))
im = np.array(render.render_dpi(r["outputs"][0], 0, 100).convert("L"))
check("hay cajas negras en la página 1", (im < 20).sum() > 3000, str((im < 20).sum()))
# la caja del DNI cubre justo donde estaba: comparar con el original
im0 = np.array(render.render_dpi(str(sp), 0, 100).convert("L")).astype(int); im1 = im.astype(int)
H = im0.shape[0]; y0, y1 = int((842 - 790) / 842 * H), int((842 - 770) / 842 * H)
from PIL import ImageFilter
sa = np.array(Image.fromarray(im0.astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))).astype(int)
sb = np.array(Image.fromarray(im1.astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))).astype(int)
c30 = int(0.30 * im0.shape[1])
check("el nombre (sin tachar) se conserva", (abs(sa[y0:y1, :c30] - sb[y0:y1, :c30]) > 60).sum() < 40)
im3 = np.array(render.render_dpi(r["outputs"][0], 2, 100).convert("L")); o3 = np.array(render.render_dpi(str(sp), 2, 100).convert("L"))
check("página girada: tiene negro nuevo", (im3 < 20).sum() > (o3 < 20).sum() + 500, f"{(im3 < 20).sum()} vs {(o3 < 20).sum()}")
check("sin opciones → error", bool(raises(lambda: core.TOOLS["redact"](str(sp), OUT, kinds=[], words=[]))))
check("sin coincidencias → error", "No he encontrado" in (raises(lambda: core.TOOLS["redact"](str(sp), OUT, kinds=[], words=["zzqxj"])) or ""))
_scan = T / "escaneo.pdf"
_im = Image.new("RGB", (600, 800), "white"); _im.save(str(_scan), "PDF", resolution=100)
check("escaneo sin texto → pide OCR", "OCR" in (raises(lambda: core.TOOLS["redact"](str(_scan), OUT, kinds=["dni"])) or ""))

print(f"\nRESULTADO: {ok} correctas, {fail} con fallo"); sys.exit(1 if fail else 0)
