"""
PDF minimo (texto en Helvetica, lineas y barras) sin dependencias.

Alcanza para el reporte ejecutivo: una libreria de PDF traeria Pillow y sus
avisos de Trivy al job. Las fuentes estandar con WinAnsiEncoding (cp1252) cubren
tildes, la ñ y el guion largo; lo que no entra en cp1252 sale como "?".
"""

from typing import List, Tuple

ANCHO, ALTO, MARGEN = 595, 842, 50  # A4 en puntos
Color = Tuple[float, float, float]
NEGRO: Color = (0.1, 0.1, 0.1)
GRIS: Color = (0.45, 0.45, 0.45)


def _cadena(texto: str) -> bytes:
    crudo = texto.encode("cp1252", errors="replace")
    return b"(" + crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _rgb(c: Color) -> str:
    return " ".join(f"{v:.2f}" for v in c)


class Pdf:
    def __init__(self):
        self.paginas: List[List[bytes]] = []
        self._nueva()

    def _nueva(self):
        self.paginas.append([])
        self.y = ALTO - MARGEN

    def espacio(self, alto: float):
        """Baja `alto` puntos; si no cabe, sigue en una pagina nueva."""
        if self.y - alto < MARGEN:
            self._nueva()
        self.y -= alto

    def fila(self, columnas: List[Tuple[float, str]], tam: float = 10, negrita: bool = False, color: Color = NEGRO):
        """Una linea de texto con cada columna en su x (desde el margen)."""
        self.espacio(tam * 1.5)
        fuente = "/F2" if negrita else "/F1"
        for x, texto in columnas:
            self.paginas[-1].append(f"BT {_rgb(color)} rg {fuente} {tam} Tf {MARGEN + x:.1f} {self.y:.1f} Td ".encode()
                                    + _cadena(texto) + b" Tj ET")

    def regla(self):
        self.espacio(6)
        self.paginas[-1].append(f"{_rgb(GRIS)} RG 0.5 w {MARGEN} {self.y:.1f} m {ANCHO - MARGEN} {self.y:.1f} l S".encode())

    def barra(self, x: float, ancho: float, fraccion: float, color: Color):
        """Barra de progreso en la ultima fila: fondo gris y `fraccion` (0-1) en color."""
        y, alto = self.y - 1, 8
        lleno = ancho * max(0.0, min(fraccion, 1.0))
        self.paginas[-1].append(f"0.9 0.9 0.9 rg {MARGEN + x:.1f} {y:.1f} {ancho:.1f} {alto} re f "
                                f"{_rgb(color)} rg {MARGEN + x:.1f} {y:.1f} {lleno:.1f} {alto} re f".encode())

    def bytes(self) -> bytes:
        objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        hojas = []
        for contenido in self.paginas:
            flujo = b"\n".join(contenido)
            objetos.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(flujo), flujo))
            objetos.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                           b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (ANCHO, ALTO, len(objetos)))
            hojas.append(len(objetos))
        objetos[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % h for h in hojas), len(hojas))

        salida, posiciones = bytearray(b"%PDF-1.4\n"), []
        for i, obj in enumerate(objetos, 1):
            posiciones.append(len(salida))
            salida += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
        xref = len(salida)
        salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        salida += b"".join(b"%010d 00000 n \n" % p for p in posiciones)
        salida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
        return bytes(salida)
