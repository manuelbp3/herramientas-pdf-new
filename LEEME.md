# Herramientas PDF (como iLovePDF, para Windows)

Unir, dividir, organizar, rotar, comprimir, reparar, marca de agua, numerar, recortar, firmar/editar,
proteger/desbloquear, OCR y conversiones (PDF↔Word/imágenes/texto, Office→PDF, imágenes→PDF, HEIC…).

**Novedades de la versión 2:** tema oscuro y cuatro herramientas nuevas:
- **PDF a Excel**: pasa las tablas de un PDF a hojas de Excel (los números salen como números).
- **Comparar dos PDF**: informe con lo añadido (verde) y lo quitado (rojo) entre dos versiones.
- **Rellenar formulario**: escribe en los campos de un PDF con formulario; opción de dejarlo fijo.
- **Tachar datos sensibles**: tapa DNI/NIE, IBAN, correos, teléfonos, tarjetas o palabras que elijas.
  Las páginas afectadas se convierten en imagen para que lo tapado no se pueda recuperar.
Todo se hace en tu ordenador; los resultados se guardan en la carpeta **Descargas**.

## Crear el .exe
1. En GitHub sube **el contenido** de esta carpeta (incluida la carpeta oculta `.github`; si no se sube al arrastrar,
   créala con "Add file → Create new file" y el nombre `.github/workflows/build-exe.yml`).
2. Pestaña **Actions** → "Crear HerramientasPDF.exe" → **Run workflow** (tarda ~10-15 min).
3. Al terminar, descarga de *Artifacts*:
   - **HerramientasPDF-Instalador**: contiene `HerramientasPDF-Instalador.exe`. Ábrelo, sigue los pasos y deja marcado
     «Crear un acceso directo en el escritorio». Se instala solo para ti, sin permisos de administrador.
   - **HerramientasPDF-Portatil**: la versión sin instalar (descomprime y abre `HerramientasPDF.exe`).

## Notas
- Windows SmartScreen puede avisar de "editor desconocido": *Más información → Ejecutar de todas formas*.
- Necesita WebView2 (ya viene en Windows 10/11 actualizados).
- Word/Excel/PowerPoint → PDF requiere tener **LibreOffice** instalado.
- OCR: se incluye Tesseract si la descarga en el build funciona; si no, instálalo aparte.
- Modo pruebas sin compilar: `pip install -r requirements.txt` y `python devserver.py` (abre el navegador).
