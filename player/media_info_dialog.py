"""Video -> Informacion del medio (Ctrl+I): archivo, duracion,
etiquetas y cada pista (codec, resolucion, cuadros/s, canales, frecuencia,
bitrate, idioma), como "Informacion del codec" de VLC."""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .formats import is_url

META_LABELS = {
    "title": "Título", "artist": "Artista", "album": "Álbum", "date": "Fecha", "genre": "Género",
    "track_number": "Pista n.º", "description": "Descripción", "copyright": "Copyright",
    "encoded_by": "Codificado por", "now_playing": "Reproduciendo ahora",
}
TRACK_LABELS = {"video": "Video", "audio": "Audio", "text": "Subtítulos", "other": "Otra"}


def format_duration(ms: int) -> str:
    seconds = max(int(ms), 0) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            text = f"{size:.0f}" if unit == "bytes" else f"{size:.1f}"
            return f"{text.replace('.', ',')} {unit}"
        size /= 1024
    return f"{num_bytes} bytes"


def _number(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"
    return text.replace(".", ",")


def describe_track(track: dict) -> list:
    """Filas (etiqueta, valor) de una pista."""
    rows = [("Códec", track.get("codec") or track.get("fourcc") or "?")]
    if track.get("type") == "video":
        if track.get("width") and track.get("height"):
            rows.append(("Resolución", f"{track['width']} × {track['height']}"))
        if track.get("fps"):
            rows.append(("Cuadros por segundo", _number(track["fps"], 3)))
    elif track.get("type") == "audio":
        channels = track.get("channels") or 0
        if channels:
            names = {1: "mono", 2: "estéreo", 6: "5.1", 8: "7.1"}
            rows.append(("Canales", f"{channels} ({names[channels]})" if channels in names else str(channels)))
        if track.get("rate"):
            rows.append(("Frecuencia de muestreo", f"{track['rate']} Hz"))
    elif track.get("type") == "text" and track.get("encoding"):
        rows.append(("Codificación", track["encoding"]))
    if track.get("bitrate"):
        rows.append(("Tasa de bits", f"{_number(track['bitrate'] / 1000, 0)} kb/s"))
    if track.get("language"):
        rows.append(("Idioma", track["language"]))
    if track.get("description"):
        rows.append(("Descripción", track["description"]))
    return rows


def media_info_sections(details: dict) -> list:
    """[(titulo de seccion, [(etiqueta, valor), ...]), ...] para mostrar."""
    path = details.get("path") or ""
    general = [("Ubicación", path)]
    if path and not is_url(path):
        general.insert(0, ("Archivo", os.path.basename(path)))
        try:
            general.append(("Tamaño", format_size(os.path.getsize(path))))
        except OSError:
            pass
    if details.get("duration_ms"):
        general.append(("Duración", format_duration(details["duration_ms"])))
    sections = [("General", general)]
    meta = details.get("meta") or {}
    if meta:
        sections.append(("Etiquetas", [(META_LABELS.get(k, k), v) for k, v in meta.items()]))
    counts = {}
    for track in details.get("tracks") or []:
        kind = track.get("type", "other")
        counts[kind] = counts.get(kind, 0) + 1
        sections.append((f"{TRACK_LABELS.get(kind, kind)} {counts[kind]}", describe_track(track)))
    return sections


def media_info_text(sections: list) -> str:
    lines = []
    for title, rows in sections:
        lines.append(title)
        lines.extend(f"  {label}: {value}" for label, value in rows)
    return "\n".join(lines)


class MediaInfoDialog(QDialog):
    def __init__(self, details: dict, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Información del medio")
        self.sections = media_info_sections(details)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Propiedad", "Valor"])
        for title, rows in self.sections:
            section = QTreeWidgetItem([title])
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            for label, value in rows:
                item = QTreeWidgetItem([label, str(value)])
                item.setToolTip(1, str(value))
                section.addChild(item)
            self.tree.addTopLevelItem(section)
            section.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        copy_button = QPushButton("Copiar")
        copy_button.clicked.connect(self.copy_to_clipboard)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.resize(560, 480)

    def copy_to_clipboard(self):
        QGuiApplication.clipboard().setText(media_info_text(self.sections))
