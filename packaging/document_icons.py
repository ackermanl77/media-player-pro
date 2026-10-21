"""Iconos de documento para los archivos asociados (8.7): una hoja con la
esquina doblada y el icono de la app encima (archivos multimedia), o con
renglones de lista y un triangulo de reproduccion (listas .m3u/.m3u8).

El .spec los incrusta como segundo y tercer grupo de iconos del .exe, que el
instalador usa como DefaultIcon (ReproductorMultimediaPro.exe,1 y ,2). Igual
que player/assets/icon.ico, los .ico generados se versionan; regenerarlos es
un paso de desarrollo:

    python packaging/document_icons.py

Se dibujan con Qt (ya es dependencia) y el contenedor .ico se escribe a mano
con imagenes PNG (Windows Vista+ las acepta en cualquier tamano), asi que no
hace falta Pillow."""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "player", "assets")
APP_ICON_PNG = os.path.join(ASSETS, "icon.png")
MEDIA_ICON = os.path.join(ASSETS, "media_document.ico")
PLAYLIST_ICON = os.path.join(ASSETS, "playlist_document.ico")
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def ico_bytes(png_images: list) -> bytes:
    """Contenedor .ico con una entrada por (lado, bytes PNG)."""
    header = struct.pack("<HHH", 0, 1, len(png_images))
    offset = len(header) + 16 * len(png_images)
    entries, data = b"", b""
    for side, png in png_images:
        byte_side = 0 if side >= 256 else side  # 0 = 256 en el formato .ico
        entries += struct.pack("<BBBBHHII", byte_side, byte_side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    return header + entries + data


def read_ico_sizes(data: bytes) -> list:
    """Lados de las imagenes de un .ico (para las pruebas)."""
    _reserved, _type, count = struct.unpack_from("<HHH", data, 0)
    sizes = []
    for i in range(count):
        width = data[6 + 16 * i]
        sizes.append(256 if width == 0 else width)
    return sizes


def _render(side: int, kind: str) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

    scale = 4  # dibujar grande y reducir: bordes suaves en 16 px
    big = side * scale
    image = QImage(big, big, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    left, top, right, bottom = big * 0.16, big * 0.04, big * 0.84, big * 0.96
    fold = big * 0.2
    pen = QPen(QColor(90, 98, 112), max(2.0, big / 64))
    p.setPen(pen)
    page = QPainterPath()
    page.addPolygon(QPolygonF([QPointF(left, top), QPointF(right - fold, top), QPointF(right, top + fold),
                               QPointF(right, bottom), QPointF(left, bottom), QPointF(left, top)]))
    p.fillPath(page, QColor(250, 251, 253))
    p.drawPath(page)
    corner = QPolygonF([QPointF(right - fold, top), QPointF(right - fold, top + fold), QPointF(right, top + fold)])
    p.setBrush(QColor(214, 220, 230))
    p.drawPolygon(corner)
    app = QImage(APP_ICON_PNG)
    if kind == "media":
        badge = big * 0.52
        target = QRectF((big - badge) / 2, big * 0.36, badge, badge)
    else:
        # Renglones de lista con un triangulo de "reproduciendo" en el primero.
        p.setPen(QPen(QColor(120, 128, 142), max(2.0, big / 22), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i, y in enumerate((0.36, 0.50, 0.64, 0.78)):
            x0 = left + big * (0.20 if i == 0 else 0.10)
            p.drawLine(QPointF(x0, big * y), QPointF(right - big * 0.10, big * y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 140, 0))
        tri = big * 0.07
        cy = big * 0.36
        p.drawPolygon(QPolygonF([QPointF(left + big * 0.07, cy - tri), QPointF(left + big * 0.07, cy + tri),
                                 QPointF(left + big * 0.07 + tri * 1.6, cy)]))
        badge = big * 0.40
        target = QRectF(right - badge * 0.85, bottom - badge * 0.85, badge, badge)
    p.drawImage(target, app)
    p.end()
    small = image.scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    small.save(buffer, "PNG")
    return bytes(buffer.data())


def make_document_icon(kind: str, out_path: str) -> str:
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        make_document_icon._app = QGuiApplication(sys.argv[:1])
    with open(out_path, "wb") as f:
        f.write(ico_bytes([(side, _render(side, kind)) for side in ICON_SIZES]))
    return out_path


if __name__ == "__main__":
    print(make_document_icon("media", MEDIA_ICON))
    print(make_document_icon("playlist", PLAYLIST_ICON))
