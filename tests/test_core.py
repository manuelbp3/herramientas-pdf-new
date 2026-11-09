"""Pruebas del núcleo. Ejecutar:  python -m tests.test_core   (desde la carpeta del proyecto)"""
import io, os, sys, tempfile, subprocess, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from app import core, render

T = Path(tempfile.mkdtemp(prefix="pdftest_"))
OUT = T / "out"; OUT.mkdir()
os.environ["APPDATA"] = str(T / "appdata")
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  OK  ", name, extra)
    else: fail += 1; print("  FALLA", name, extra)

def make_pdf(path, pages=3, size=(595, 842), rot=None):
    c = canvas.Canvas(str(path), pagesize=size)
    for i in range(pages):
        c.setFont("Helvetica", 24); c.drawString(72, size[1]-100, f"Pagina {i+1} de {pages}")
        c.rect(40, 40, size[0]-80, size[1]-80)
        c.showPage()
    c.save()
    if rot:
        from pypdf import PdfWriter
        r = PdfReader(str(path)); w = PdfWriter()
        for p in r.pages: p.rotate(rot); w.add_page(p)
        w.write(str(path))

def dark_bbox(pdf, idx=0, dpi=50):
    img = render.render_dpi(str(pdf), idx, dpi).convert("L"); return img.size

a, b, c3 = T/"a.pdf", T/"b.pdf", T/"c.pdf"
make_pdf(a, 3); make_pdf(b, 2); make_pdf(c3, 4, rot=90)

print("Unir"); r = core.merge([str(a), str(b)], OUT); check("5 páginas", len(PdfReader(r["outputs"][0]).pages) == 5)
try: core.merge([str(a)], OUT); check("error con un solo archivo", False)
except core.ToolError: check("error con un solo archivo", True)

print("Rangos")
check("parse", [g[1] for g in core.parse_ranges("1-2, 4, 3-", 5)] == [[0,1],[3],[2,3,4]])
for bad in ("0", "9", "3-1", "x"):
    try: core.parse_ranges(bad, 5); check("rango malo "+bad, False)
    except core.ToolError: check("rango malo "+bad, True)

print("Dividir")
r = core.split(str(a), OUT, mode="all"); check("una por archivo", len(r["outputs"]) == 3 and Path(r["folder"]).is_dir())
r = core.split(str(c3), OUT, mode="every", n=3); check("cada 3 -> 2 archivos", len(r["outputs"]) == 2, [len(PdfReader(o).pages) for o in r["outputs"]])
r = core.split(str(c3), OUT, mode="ranges", value="1-2, 4"); check("rangos", [len(PdfReader(o).pages) for o in r["outputs"]] == [2,1])
r = core.split(str(c3), OUT, mode="extract", value="2,4"); check("extraer", len(PdfReader(r["outputs"][0]).pages) == 2)

print("Organizar / girar / eliminar")
r = core.organize(str(a), OUT, pages=[{"i":2,"rot":0},{"i":0,"rot":90}])
rd = PdfReader(r["outputs"][0]); check("orden y 2 páginas", len(rd.pages)==2 and "Pagina 3" in rd.pages[0].extract_text() and "Pagina 1" in rd.pages[1].extract_text())
check("rotación aplicada", rd.pages[1].rotation == 90)
r = core.organize(str(c3), OUT, pages=[{"i":0,"rot":90}]); check("rotación sobre ya girada = 180", PdfReader(r["outputs"][0]).pages[0].rotation == 180)
r = core.rotate(str(a), OUT, degrees=270); check("girar todo", all(p.rotation == 270 for p in PdfReader(r["outputs"][0]).pages))
try: core.organize(str(a), OUT, pages=[]); check("sin páginas -> error", False)
except core.ToolError: check("sin páginas -> error", True)

print("Comprimir")
rng = np.random.default_rng(1)
arr = (rng.integers(0, 255, (1800, 2400, 3), dtype=np.uint8) * 0 + np.linspace(0, 255, 2400, dtype=np.uint8)[None, :, None]).astype(np.uint8)
arr = np.clip(arr.astype(int) + rng.integers(-25, 25, arr.shape), 0, 255).astype(np.uint8)
big = T/"big.pdf"; Image.fromarray(arr).save(T/"photo.png")
cc = canvas.Canvas(str(big), pagesize=(595, 842)); cc.drawImage(str(T/"photo.png"), 20, 200, 555, 416); cc.drawString(30, 800, "Texto de prueba"); cc.showPage(); cc.save()
for lvl in ("low", "medium", "high"):
    r = core.compress(str(big), OUT, level=lvl)
    if r["outputs"]:
        o = r["outputs"][0]; check(f"comprimir {lvl}", Path(o).stat().st_size < big.stat().st_size, r["message"])
        check(f"  abre y conserva texto ({lvl})", "Texto de prueba" in PdfReader(o).pages[0].extract_text())
    else: check(f"comprimir {lvl}", False, r["message"])
r = core.compress(str(a), OUT); check("ya optimizado: no empeora", r["outputs"] == [] or Path(r["outputs"][0]).stat().st_size < a.stat().st_size, r["message"])

print("Reparar"); r = core.repair(str(a), OUT); check("reparar", len(PdfReader(r["outputs"][0]).pages) == 3)
raw = a.read_bytes(); trunc = T/"trunc.pdf"; trunc.write_bytes(raw[:-40])
try: r = core.repair(str(trunc), OUT); check("reparar PDF dañado", len(PdfReader(r["outputs"][0]).pages) >= 1)
except core.ToolError as e: check("reparar PDF dañado (mensaje claro)", True, str(e)[:60])

print("Seguridad")
r = core.protect(str(a), OUT, password="secreto"); p = r["outputs"][0]
check("protegido", PdfReader(p).is_encrypted)
try: core.merge([p, str(b)], OUT); check("unir protegido -> error claro", False)
except core.ToolError as e: check("unir protegido -> error claro", "contraseña" in str(e))
try: core.unlock(p, OUT, password="mal"); check("contraseña incorrecta", False)
except core.ToolError as e: check("contraseña incorrecta", "no es correcta" in str(e))
r = core.unlock(p, OUT, password="secreto"); check("desproteger", not PdfReader(r["outputs"][0]).is_encrypted)

def dark_centroid(pdf, idx, dpi=40):
    img = np.array(render.render_dpi(str(pdf), idx, dpi).convert("L")); ys, xs = np.where(img < 170)
    return img.shape, (xs.mean()/img.shape[1], ys.mean()/img.shape[0]) if len(xs) else None

print("Marca de agua (también en páginas giradas)")
blank = T/"blank.pdf"; cb = canvas.Canvas(str(blank), pagesize=(595, 842)); cb.showPage(); cb.save()
blank90 = T/"blank90.pdf"; shutil.copy(blank, blank90)
from pypdf import PdfWriter
rr = PdfReader(str(blank)); ww = PdfWriter(); pg = rr.pages[0]; pg.rotate(90); ww.add_page(pg); ww.write(str(blank90))
for name, f in (("normal", blank), ("girada 90", blank90)):
    r = core.watermark(str(f), OUT, text="CONFIDENCIAL", size=80, opacity=1, angle=0, color="#000000")
    shp, cen = dark_centroid(r["outputs"][0], 0)
    check(f"marca centrada ({name})", cen and abs(cen[0]-.5) < .05 and abs(cen[1]-.5) < .05, f"{shp} centro={tuple(round(v,2) for v in cen) if cen else None}")
r = core.watermark(str(a), OUT, text="Confidencial ñandú €", size=50); check("acentos y símbolos", "Pagina 1" in PdfReader(r["outputs"][0]).pages[0].extract_text())
try: core.watermark(str(a), OUT, text=" "); check("texto vacío -> error", False)
except core.ToolError: check("texto vacío -> error", True)

print("Numerar páginas")
r = core.page_numbers(str(a), OUT, position="bottom-center", fmt="Página {n} de {total}", start=1); rd = PdfReader(r["outputs"][0])
check("texto del número", "Página 2 de 3" in rd.pages[1].extract_text().replace("\n", " "), rd.pages[1].extract_text()[-30:].replace("\n"," "))
r = core.page_numbers(str(a), OUT, fmt="{n}", start=5, skip_first=True); rd = PdfReader(r["outputs"][0])
check("saltar portada", "5" not in rd.pages[0].extract_text().split("Pagina 1 de 3")[-1] and "5" in rd.pages[1].extract_text())
r = core.page_numbers(str(c3), OUT, position="top-right", fmt="N{n}"); shp, cen = dark_centroid(r["outputs"][0], 0)
img = np.array(render.render_dpi(r["outputs"][0], 0, 40).convert("L")); H, W = img.shape
# página girada 90: lo visible es apaisado; el número arriba-derecha debe quedar en la esquina superior derecha visible
region = img[: int(H*.12), int(W*.8):]; check("número arriba-derecha en página girada", (region < 140).sum() > 3, f"{W}x{H}")

print("Recortar")
r = core.crop(str(a), OUT, left=20, top=10, right=20, bottom=10); w0, h0 = dark_bbox(a); w1, h1 = dark_bbox(r["outputs"][0])
check("recorte normal", abs((w0-w1)-(40/25.4*50)) < 3 and abs((h0-h1)-(20/25.4*50)) < 3, f"{w0}x{h0} -> {w1}x{h1}")
r = core.crop(str(c3), OUT, left=30, top=0, right=0, bottom=0); w0, h0 = dark_bbox(c3); w1, h1 = dark_bbox(r["outputs"][0])
check("recorte en página girada (quita ancho visible)", abs((w0-w1)-(30/25.4*50)) < 3 and h0 == h1, f"{w0}x{h0} -> {w1}x{h1}")
try: core.crop(str(a), OUT); check("sin márgenes -> error", False)
except core.ToolError: check("sin márgenes -> error", True)

print("Firmar / añadir texto")
sig = Image.new("RGBA", (400, 160), (0, 0, 0, 0)); d = ImageDraw.Draw(sig); d.line([(10,120),(100,20),(200,130),(380,40)], fill=(0,0,120,255), width=10)
sp = T/"sig.png"; sig.save(sp)
items = [{"type":"image","image":str(sp),"x":.1,"y":.1,"w":.3,"pages":[0]}, {"type":"text","text":"Firmado: Ana","x":.5,"y":.5,"fs":.05,"color":"#000000","pages":[0,2]}]
r = core.stamp(str(a), OUT, items=items); rd = PdfReader(r["outputs"][0])
check("texto añadido en páginas 1 y 3", "Firmado: Ana" in rd.pages[0].extract_text() and "Firmado: Ana" in rd.pages[2].extract_text() and "Firmado: Ana" not in rd.pages[1].extract_text())
im = np.array(render.render_dpi(r["outputs"][0], 0, 50).convert("RGB")).astype(int); H, W, _ = im.shape
blue = (im[:,:,2] > 90) & (im[:,:,0] < 60) & (im[:,:,1] < 60); ys, xs = np.where(blue)
check("firma en la posición pedida (esquina sup. izq.)", len(xs) > 50 and .08 < xs.min()/W < .16 and .42 > xs.max()/W > .34 and .08 < ys.min()/H < .2, f"x {xs.min()/W:.2f}-{xs.max()/W:.2f} y {ys.min()/H:.2f}-{ys.max()/H:.2f}")
r = core.stamp(str(c3), OUT, items=[{"type":"image","image":str(sp),"x":.1,"y":.1,"w":.3,"pages":[0]}])
im = np.array(render.render_dpi(r["outputs"][0], 0, 50).convert("RGB")).astype(int); H, W, _ = im.shape
blue = (im[:,:,2] > 90) & (im[:,:,0] < 60) & (im[:,:,1] < 60); ys, xs = np.where(blue)
check("firma en página girada 90: sigue en esquina sup. izq. visible", len(xs) > 50 and xs.min()/W < .2 and ys.min()/H < .25, f"{W}x{H} x {xs.min()/W:.2f}-{xs.max()/W:.2f} y {ys.min()/H:.2f}-{ys.max()/H:.2f}")
try: core.stamp(str(a), OUT, items=[]); check("sin elementos -> error", False)
except core.ToolError: check("sin elementos -> error", True)

print("Firmas guardadas")
sid = core.save_signature_dataurl("data:image/png;base64," + __import__("base64").b64encode(sp.read_bytes()).decode())
check("guardar firma dibujada", sid in core.list_signatures() and core.signature_path(sid))
photo = Image.new("RGB", (600, 300), "white"); ImageDraw.Draw(photo).line([(40,200),(200,60),(400,220),(560,80)], fill=(30,30,30), width=9); photo.save(T/"firma_foto.jpg")
sid2 = core.save_signature_from_file(str(T/"firma_foto.jpg")); im2 = Image.open(core.signature_path(sid2))
check("firma desde foto: fondo transparente", im2.mode == "RGBA" and im2.getpixel((2, 2))[3] == 0, im2.size)
try: core.save_signature_image(Image.new("RGBA", (50, 50), (0,0,0,0))); check("firma vacía -> error", False)
except core.ToolError: check("firma vacía -> error", True)
core.delete_signature(sid); check("borrar firma", core.signature_path(sid) is None)
check("id malicioso no accede a rutas", core.signature_path("../../etc/passwd") is None)

print("Convertir")
r = core.pdf_to_text(str(a), OUT); check("PDF a texto", "Pagina 2 de 3" in Path(r["outputs"][0]).read_text(encoding="utf-8"))
try: core.pdf_to_text(str(T/"photo_only.pdf") if False else str(blank), OUT); check("PDF sin texto -> aviso OCR", False)
except core.ToolError as e: check("PDF sin texto -> aviso OCR", "OCR" in str(e))
r = core.pdf_to_images(str(a), OUT, fmt="jpg", dpi=60); check("PDF a JPG (3 págs -> carpeta)", len(r["outputs"]) == 3 and Path(r["folder"]).is_dir())
r = core.pdf_to_images(str(blank), OUT, fmt="png", dpi=60); check("PDF de 1 página a PNG", r["outputs"][0].endswith(".png"))
im_a = T/"x.png"; Image.new("RGBA", (800, 600), (200, 30, 30, 120)).save(im_a); im_b = T/"y.jpg"; Image.new("RGB", (500, 900), (30, 30, 200)).save(im_b)
r = core.images_to_pdf([str(im_a), str(im_b)], OUT, page="a4", margin="small"); rd = PdfReader(r["outputs"][0])
check("imágenes a PDF: 2 páginas, apaisada y vertical", len(rd.pages) == 2 and rd.pages[0].mediabox.width > rd.pages[0].mediabox.height and rd.pages[1].mediabox.width < rd.pages[1].mediabox.height)
r = core.images_to_pdf([str(im_b)], OUT, page="original", margin="none"); check("tamaño original", abs(float(PdfReader(r["outputs"][0]).pages[0].mediabox.width) - 375) < 1)
for t in ("jpg", "png", "webp", "bmp", "tiff"):
    r = core.convert_image(str(im_a), OUT, target=t); check("imagen -> "+t, Image.open(r["outputs"][0]).size == (800, 600))
try: core.convert_image(str(T/"nada.png"), OUT); check("archivo inexistente -> error", False)
except core.ToolError: check("archivo inexistente -> error", True)

print("Word a PDF (LibreOffice)")
if core.find_soffice():
    import docx
    d = docx.Document(); d.add_paragraph("Hola desde Word"); dp = T/"doc.docx"; d.save(dp)
    r = core.office_to_pdf(str(dp), OUT); check("docx -> pdf", "Hola desde Word" in PdfReader(r["outputs"][0]).pages[0].extract_text())
else: print("  (sin LibreOffice, omitido)")

print("OCR")
if core.ocr_available():
    scan = Image.new("RGB", (1700, 2200), "white"); dd = ImageDraw.Draw(scan)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 70)
    dd.text((150, 300), "Factura numero 4821", fill="black", font=f); dd.text((150, 500), "Total pagado cien euros", fill="black", font=f)
    sc = T/"scan.pdf"; scan.save(sc, "PDF", resolution=200)
    check("el escaneo no tiene texto", not (PdfReader(str(sc)).pages[0].extract_text() or "").strip())
    r = core.ocr(str(sc), OUT, lang="spa+eng", output="both")
    txt = (PdfReader(r["outputs"][0]).pages[0].extract_text() or "").lower()
    check("OCR: PDF buscable", "factura" in txt and "4821" in txt, txt[:50].replace("\n", " "))
    check("OCR: tamaño de página conservado", abs(float(PdfReader(r["outputs"][0]).pages[0].mediabox.width) - 612) < 6, str(PdfReader(r["outputs"][0]).pages[0].mediabox.width))
    check("OCR: archivo txt", "total" in Path(r["outputs"][1]).read_text(encoding="utf-8").lower())
else: print("  (sin Tesseract, omitido)")

print(f"\nRESULTADO: {ok} correctas, {fail} con fallo"); shutil.rmtree(T, ignore_errors=True); sys.exit(1 if fail else 0)
