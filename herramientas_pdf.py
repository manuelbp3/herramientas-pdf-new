import os
import sys
import traceback


def _registrar_error():
    """Si algo falla al abrir, lo guarda en un archivo y lo muestra en una ventana."""
    texto = traceback.format_exc()
    try:
        carpeta = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "HerramientasPDF")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, "error.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
    except Exception:
        ruta = "(no se pudo guardar)"
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "La aplicacion no pudo abrirse.\n\nDetalle guardado en:\n" + ruta + "\n\n" + texto[-900:],
            "Herramientas PDF", 0x10)
    except Exception:
        print(texto, file=sys.stderr)


if __name__ == "__main__":
    try:
        from app.main import main
        main()
    except Exception:
        _registrar_error()
        sys.exit(1)
