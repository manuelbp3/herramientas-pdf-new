"""Prueba de la interfaz en Chrome contra el modo de pruebas (devserver). Requiere playwright."""
import os, sys, time, subprocess, tempfile, shutil, json
from pathlib import Path
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
T = Path(tempfile.mkdtemp(prefix="uitest_")); HOME = T / "home"; (HOME / "Downloads").mkdir(parents=True)
SHOTS = Path(os.environ.get("SHOTS", T / "shots")); SHOTS.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, HOME=str(HOME), APPDATA=str(T / "appdata"))
srv = subprocess.Popen([sys.executable, "devserver.py", "8791"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(1.5)
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  OK  ", name, extra)
    else: fail += 1; print("  FALLA", name, extra)

def mkpdf(path, n, label):
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    for i in range(n):
        c.setFont("Helvetica-Bold", 40); c.drawString(70, 740, f"{label} pag {i+1}"); c.setFont("Helvetica", 14)
        for k in range(12): c.drawString(70, 690 - k * 22, "Lorem ipsum dolor sit amet consectetur adipiscing elit")
        c.showPage()
    c.save()
A, B, C = T / "informe.pdf", T / "anexo.pdf", T / "contrato.pdf"
mkpdf(A, 2, "Informe"); mkpdf(B, 3, "Anexo"); mkpdf(C, 5, "Contrato")
# archivos para las herramientas nuevas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
TAB, V1, V2, FORM, DATOS = T / "tabla.pdf", T / "v1.pdf", T / "v2.pdf", T / "solicitud.pdf", T / "datos.pdf"
SimpleDocTemplate(str(TAB), pagesize=A4).build([Table([["Concepto", "Unidades", "Total"], ["Tornillos", "100", "25,00"], ["Tuercas", "50", "1.020,50"]], style=TableStyle([("GRID", (0, 0), (-1, -1), .6, colors.black)]))])
def _doc(path, lines):
    c = canvas.Canvas(str(path), pagesize=A4); c.setFont("Helvetica", 14)
    for k, ln in enumerate(lines): c.drawString(72, 780 - k * 24, ln)
    c.save()
_doc(V1, ["Contrato de alquiler", "Precio mensual: 800 euros", "Duracion: 12 meses"]); _doc(V2, ["Contrato de alquiler", "Precio mensual: 950 euros", "Duracion: 12 meses"])
_doc(DATOS, ["Cliente: Juan Perez  DNI 12345678Z", "Correo: juan.perez@ejemplo.com", "Telefono: 612 345 678", "Nota: informacion Confidencial"])
_c = canvas.Canvas(str(FORM), pagesize=A4); _f = _c.acroForm; _c.setFont("Helvetica", 12); _c.drawString(72, 790, "Solicitud")
_f.textfield(name="nombre", x=72, y=740, width=250, height=22, forceBorder=True)
_f.checkbox(name="acepto", x=72, y=700, size=18, checked=False, forceBorder=True)
_f.choice(name="pais", x=72, y=660, width=150, height=22, options=["España", "Francia", "Italia"], value="España", forceBorder=True)
_c.save()
img = T / "foto.png"; Image.new("RGB", (900, 600), (60, 120, 200)).save(img)
downloads = lambda: sorted(p.name for p in (HOME / "Downloads").iterdir())
errors = []
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 1240, "height": 820})
        pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto("http://127.0.0.1:8791/"); pg.wait_for_selector(".card")
        ntools = pg.locator(".card").count(); check("inicio: tarjetas de herramientas", ntools == 24, ntools)
        pg.screenshot(path=SHOTS / "1_inicio.png")
        pg.fill(".search input", "firm"); check("buscador filtra", pg.locator(".card").count() == 1)
        pg.fill(".search input", ""); 

        print("Unir PDF")
        pg.click("text=Unir PDF"); pg.wait_for_selector(".drop")
        check("run desactivado sin archivos", pg.is_disabled("#run"))
        pg.evaluate("p=>window.__dropped(p)", [str(A), str(B), str(T / "malo.txt")])
        pg.wait_for_selector(".fcard"); time.sleep(.8)
        check("2 tarjetas (el .txt se ignora con aviso)", pg.locator(".fcard").count() == 2 and pg.locator(".toast.err").count() == 1)
        check("miniatura cargada", pg.locator(".fcard .th img").count() == 2)
        pg.screenshot(path=SHOTS / "2_unir.png")
        b1 = pg.locator(".fcard").nth(0).bounding_box(); b2 = pg.locator(".fcard").nth(1).bounding_box()
        pg.mouse.move(b1["x"] + 60, b1["y"] + 80); pg.mouse.down(); pg.mouse.move(b2["x"] + 100, b2["y"] + 80, steps=8); pg.mouse.move(b2["x"] + 110, b2["y"] + 82, steps=3); pg.mouse.up()
        names = pg.locator(".fcard .nm").all_inner_texts(); check("arrastrar cambia el orden", names == ["anexo.pdf", "informe.pdf"], names)
        check("números de orden actualizados", pg.locator(".fcard .ord").all_inner_texts() == ["1", "2"])
        pg.click("#run"); pg.wait_for_selector(".result"); time.sleep(.3)
        check("resultado correcto", pg.locator(".result:not(.bad)").count() == 1 and "unido.pdf" in downloads(), downloads())
        txt = (PdfReader(str(HOME / "Downloads" / "unido.pdf")).pages[0].extract_text())
        check("el primero es Anexo (orden respetado)", "Anexo pag 1" in txt)
        pg.screenshot(path=SHOTS / "3_resultado.png")
        pg.click("text=Todas las herramientas")

        print("Dividir / validaciones")
        pg.click("text=Dividir PDF"); pg.evaluate("p=>window.__dropped(p)", [str(C)]); pg.wait_for_selector(".fcard")
        pg.click("#run"); check("rangos vacíos -> aviso", pg.locator(".toast.err").count() == 1)
        pg.fill("#f_value", "1-2, 5"); pg.click("#run"); pg.wait_for_selector(".result")
        check("dividido en carpeta", any(n.startswith("contrato_dividido") for n in downloads()), downloads())
        pg.click("text=Todas las herramientas")

        print("Proteger")
        pg.click("text=Proteger con contraseña"); pg.evaluate("p=>window.__dropped(p)", [str(A)]); pg.wait_for_selector(".fcard")
        pg.fill("#f_password", "abc"); pg.fill("#f_password2", "abd"); pg.click("#run")
        check("contraseñas distintas -> aviso", "no coinciden" in pg.locator(".toast").inner_text())
        pg.fill("#f_password2", "abc"); pg.click("#run"); pg.wait_for_selector(".result")
        check("protegido", PdfReader(str(HOME / "Downloads" / "informe_protegido.pdf")).is_encrypted)
        pg.click("text=Todas las herramientas")
        pg.click("text=Comprimir PDF"); pg.evaluate("p=>window.__dropped(p)", [str(HOME / "Downloads" / "informe_protegido.pdf")]); pg.wait_for_selector(".fcard")
        check("PDF protegido avisa en la tarjeta", pg.locator(".fcard .warn").count() == 1)
        pg.click("#run"); check("y bloquea la herramienta", "protegido" in pg.locator(".toast").inner_text())
        pg.click("text=← Herramientas")

        print("Marca de agua (opciones dinámicas)")
        pg.click("text=Marca de agua"); pg.evaluate("p=>window.__dropped(p)", [str(A)]); pg.wait_for_selector(".fcard")
        pg.fill("#f_text", "BORRADOR"); pg.select_option("#f_position", "top"); check("el giro se oculta si no es centro", pg.locator("#f_angle").count() == 0)
        pg.screenshot(path=SHOTS / "4_marca.png")
        pg.click("#run"); pg.wait_for_selector(".result"); check("marca aplicada", "BORRADOR" in PdfReader(str(HOME / "Downloads" / "informe_marca.pdf")).pages[0].extract_text())
        pg.click("text=Todas las herramientas")

        print("Imágenes a PDF")
        pg.click("text=Imágenes a PDF"); pg.evaluate("p=>window.__dropped(p)", [str(img)]); pg.wait_for_selector(".fcard"); time.sleep(.5)
        pg.click("#run"); pg.wait_for_selector(".result"); check("imagen a pdf", "foto.pdf" in downloads())
        pg.click("text=Todas las herramientas")

        print("Organizar páginas")
        pg.click("text=Organizar páginas"); pg.evaluate("p=>window.__dropped(p)", [str(C)]); pg.wait_for_selector(".tile"); time.sleep(1.5)
        check("5 miniaturas con imagen", pg.locator(".tile").count() == 5 and pg.locator(".tile img[src]").count() >= 5, pg.locator(".tile img[src]").count())
        pg.screenshot(path=SHOTS / "5_organizar.png")
        t = pg.locator(".tile")
        t.nth(1).locator("button.del").click(); t.nth(2).locator("button").nth(1).click()
        check("resumen: 4 de 5", "4" in pg.locator(".stat").inner_text())
        b1 = t.nth(0).bounding_box(); b4 = t.nth(3).bounding_box()
        pg.mouse.move(b1["x"] + 80, b1["y"] + 60); pg.mouse.down(); pg.mouse.move(b4["x"] + 90, b4["y"] + 60, steps=10); pg.mouse.move(b4["x"] + 100, b4["y"] + 62, steps=3); pg.mouse.up()
        order = [int(x) for x in pg.locator(".tile").evaluate_all("els=>els.map(e=>e.dataset.i)")]; check("arrastrar página 1 hacia el final", order[0] != 0 and order.index(0) >= 2, order)
        pg.click("#run"); pg.wait_for_selector(".result")
        rd = PdfReader(str(HOME / "Downloads" / "contrato_organizado.pdf")); texts = [pp.extract_text() for pp in rd.pages]
        check("4 páginas, sin la 2", len(rd.pages) == 4 and not any("pag 2" in x for x in texts), [x[:18] for x in texts])
        check("la página 3 está girada 90°", any(pp.rotation == 90 and "pag 3" in pp.extract_text() for pp in rd.pages))
        check("orden = el de pantalla", [int(x.split("pag ")[1][0]) - 1 for x in texts] == [i for i in order if i != 1], [int(x.split("pag ")[1][0]) - 1 for x in texts])
        pg.click("text=Todas las herramientas")

        print("Eliminar páginas por rango")
        pg.click("text=Eliminar páginas"); pg.evaluate("p=>window.__dropped(p)", [str(C)]); pg.wait_for_selector(".tile")
        pg.fill("#delrange", "2-3, 5"); pg.click("text=Marcar para eliminar")
        check("rango marcado", pg.locator(".tile.removed").count() == 3 and "2" in pg.locator(".stat").inner_text())
        pg.fill("#delrange", "9"); pg.click("text=Marcar para eliminar"); check("rango fuera -> aviso", pg.locator(".toast.err").count() == 1)
        pg.click("#run"); pg.wait_for_selector(".result"); check("2 páginas", len(PdfReader(str(HOME / "Downloads" / "contrato_sin_paginas.pdf")).pages) == 2)
        pg.click("text=Todas las herramientas")

        print("Firmar: dibujar firma y colocarla")
        pg.click("text=Firmar y editar PDF"); pg.evaluate("p=>window.__dropped(p)", [str(C)]); pg.wait_for_selector("#pimg[src]"); time.sleep(.8)
        check("editor muestra página 1 de 5", "Página 1 de 5" in pg.inner_text("#pn"))
        check("sin firmas: guardar desactivado", pg.is_disabled("#run"))
        pg.click("text=Dibujar firma"); pg.wait_for_selector("#pad"); box = pg.locator("#pad").bounding_box()
        pts = [(0.1, .7), (.25, .2), (.4, .8), (.55, .25), (.7, .75), (.88, .3)]
        pg.mouse.move(box["x"] + box["width"] * pts[0][0], box["y"] + box["height"] * pts[0][1]); pg.mouse.down()
        for x, y in pts[1:]: pg.mouse.move(box["x"] + box["width"] * x, box["y"] + box["height"] * y, steps=12)
        pg.mouse.up(); pg.screenshot(path=SHOTS / "6_dibujar.png"); pg.click("text=Guardar firma"); pg.wait_for_selector(".it"); time.sleep(.3)
        check("firma guardada y colocada", pg.locator(".sig").count() == 1 and pg.locator(".it").count() == 1)
        fr = pg.locator("#frame").bounding_box(); it = pg.locator(".it").first.bounding_box()
        pg.mouse.move(it["x"] + it["width"] / 2, it["y"] + it["height"] / 2); pg.mouse.down()
        pg.mouse.move(fr["x"] + fr["width"] * .3, fr["y"] + fr["height"] * .3, steps=10); pg.mouse.up()
        it2 = pg.locator(".it").first.bounding_box(); check("arrastrar mueve la firma", abs((it2["x"] - fr["x"]) / fr["width"] - .3 + it["width"] / fr["width"] / 2) < .08, f"x={(it2['x']-fr['x'])/fr['width']:.2f}")
        rs = pg.locator(".it .rs").bounding_box(); pg.mouse.move(rs["x"] + 10, rs["y"] + 10); pg.mouse.down(); pg.mouse.move(rs["x"] + 90, rs["y"] + 40, steps=6); pg.mouse.up()
        it3 = pg.locator(".it").first.bounding_box(); check("el círculo cambia el tamaño", it3["width"] > it2["width"] + 40, f"{it2['width']:.0f}->{it3['width']:.0f}")
        pg.select_option("#scope", "last")
        check("ámbito 'última' => desaparece de página 1", pg.locator(".it").count() == 0)
        pg.click("text=Aa Texto"); pg.fill("#txt", "Madrid, a 7 de noviembre"); pg.select_option("#scope", "all")
        check("texto visible", "Madrid" in pg.locator(".it.text").inner_text())
        pg.click("#next"); time.sleep(.7); check("página 2: el texto (todas) sigue; la firma (última) no", pg.locator(".it.text").count() == 1 and pg.locator(".it.img").count() == 0)
        for _ in range(3): pg.click("#next"); time.sleep(.5)
        check("página 5: aparecen firma y texto", pg.locator(".it.img").count() == 1 and pg.locator(".it.text").count() == 1)
        pg.screenshot(path=SHOTS / "7_editor.png")
        pg.click("#run"); pg.wait_for_selector(".result"); out = HOME / "Downloads" / "contrato_firmado.pdf"
        rd = PdfReader(str(out)); check("PDF firmado: texto en las 5 páginas", all("Madrid, a 7 de noviembre" in pp.extract_text() for pp in rd.pages))
        pg.screenshot(path=SHOTS / "8_resultado_firma.png")
        pg.click("text=Hacer otro"); pg.wait_for_selector(".drop")
        pg.evaluate("p=>window.__dropped(p)", [str(A)]); pg.wait_for_selector("#pimg[src]"); time.sleep(.5)
        check("la firma guardada sigue disponible en otro documento", pg.locator(".sig").count() == 1)


        print("Herramientas nuevas")
        pg.click("text=← Herramientas"); pg.wait_for_selector(".card")
        card = lambda name: pg.click(f'.card:has-text("{name}")')
        card("PDF a Excel"); pg.wait_for_selector(".drop")
        pg.evaluate("p=>window.__dropped(p)", [str(TAB)]); pg.wait_for_selector(".fcard"); pg.screenshot(path=SHOTS / "10_pdf_a_excel.png")
        pg.click("#run"); pg.wait_for_selector(".result"); time.sleep(.3)
        from openpyxl import load_workbook
        xl = HOME / "Downloads" / "tabla.xlsx"
        check("PDF a Excel: se crea el .xlsx", xl.exists() and pg.locator(".result:not(.bad)").count() == 1, downloads())
        rows = [[c.value for c in r] for r in load_workbook(xl).worksheets[0].iter_rows()]
        check("PDF a Excel: números convertidos", rows[1][1] == 100 and rows[2][2] == 1020.5, str(rows))
        pg.click("text=Todas las herramientas"); pg.wait_for_selector(".card")

        card("Comparar dos PDF"); pg.wait_for_selector(".drop")
        pg.evaluate("p=>window.__dropped(p)", [str(V1)]); pg.wait_for_selector(".fcard")
        pg.click("#run"); time.sleep(.3); check("Comparar: con un solo PDF avisa", pg.locator(".toast.err").count() == 1)
        pg.evaluate("p=>window.__dropped(p)", [str(V2)]); time.sleep(.6)
        check("Comparar: etiquetas Original / Modificado", pg.locator(".fcard .ord").all_inner_texts() == ["Original", "Modificado"], pg.locator(".fcard .ord").all_inner_texts())
        pg.screenshot(path=SHOTS / "11_comparar.png")
        pg.click("#run"); pg.wait_for_selector(".result"); time.sleep(.3)
        cmp_files = [n for n in downloads() if n.startswith("Comparacion_")]
        check("Comparar: se crea el informe", pg.locator(".result:not(.bad)").count() == 1 and len(cmp_files) == 1, downloads())
        pg.screenshot(path=SHOTS / "12_comparar_resultado.png")
        pg.click("text=Todas las herramientas"); pg.wait_for_selector(".card")

        card("Rellenar formulario"); pg.wait_for_selector(".drop")
        check("Formulario: sin archivo explica qué hacer", "Elige un PDF con formulario" in pg.locator("#opts").inner_text())
        pg.evaluate("p=>window.__dropped(p)", [str(FORM)]); pg.wait_for_selector('[id="f_v:nombre"]'); time.sleep(.3)
        check("Formulario: 3 campos + opción de dejarlo fijo", pg.locator("#opts .field").count() == 4, pg.locator("#opts .field").count())
        pg.fill('[id="f_v:nombre"]', "Manuel García"); pg.check('[id="f_v:acepto"]'); pg.select_option('[id="f_v:pais"]', "Francia")
        pg.screenshot(path=SHOTS / "13_formulario.png")
        pg.click("#run"); pg.wait_for_selector(".result"); time.sleep(.3)
        got = PdfReader(str(HOME / "Downloads" / "solicitud_rellenado.pdf")).get_fields()
        check("Formulario: valores guardados", got["nombre"].get("/V") == "Manuel García" and str(got["pais"].get("/V")) == "Francia" and str(got["acepto"].get("/V")) not in ("", "/Off"), {k: str(v.get("/V")) for k, v in got.items()})
        pg.click("text=Todas las herramientas"); pg.wait_for_selector(".card")

        card("Tachar datos sensibles"); pg.wait_for_selector(".drop")
        pg.evaluate("p=>window.__dropped(p)", [str(DATOS)]); pg.wait_for_selector(".fcard"); time.sleep(.5)
        pg.fill("#f_words", "Confidencial"); pg.screenshot(path=SHOTS / "14_tachar.png")
        pg.click("#run"); pg.wait_for_selector(".result"); time.sleep(.5)
        red = HOME / "Downloads" / "datos_tachado.pdf"
        check("Tachar: se crea el PDF", red.exists() and pg.locator(".result:not(.bad)").count() == 1, downloads())
        tx = PdfReader(str(red)).pages[0].extract_text() or ""
        check("Tachar: ya no queda el texto sensible", not any(w in tx for w in ("12345678Z", "juan.perez", "612 345", "Confidencial")), tx[:80])
        pg.screenshot(path=SHOTS / "15_tachar_resultado.png")
        pg.click("text=Todas las herramientas"); pg.wait_for_selector(".card")
        pg.click('.card:has-text("Tachar datos sensibles")'); pg.wait_for_selector(".drop")
        pg.evaluate("p=>window.__dropped(p)", [str(DATOS)]); pg.wait_for_selector(".fcard")
        for k in ("dni", "iban", "email", "phone", "card"): pg.uncheck(f"#f_k_{k}")
        pg.fill("#f_words", ""); pg.click("#run"); time.sleep(.3)
        check("Tachar: sin nada marcado avisa", pg.locator(".toast.err").count() == 1)
        pg.click("text=← Herramientas"); pg.wait_for_selector(".card")

        print("Inicio de nuevo / modo oscuro")
        pg.wait_for_selector(".card")
        pg.emulate_media(color_scheme="dark"); pg.screenshot(path=SHOTS / "9_oscuro.png"); pg.emulate_media(color_scheme="light")
        br.close()
except Exception:
    import traceback; traceback.print_exc(); fail += 1
finally:
    srv.terminate()
    check("sin errores de JavaScript", not errors, errors[:3])
    print(f"\nRESULTADO: {ok} correctas, {fail} con fallo"); print("capturas en", SHOTS)
    if "--keep" not in sys.argv: shutil.rmtree(T / "home", ignore_errors=True)
    sys.exit(1 if fail else 0)
