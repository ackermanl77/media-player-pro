"""Tema (Sistema / Oscuro / Claro), colores de las superpuestas e iconos.

Antes no se fijaba ningun estilo: la app seguia lo que diera la
plataforma (en Windows 10, "windowsvista", solo claro: una UI clara
enmarcando el video negro) con estilos sueltos en linea y los iconos
estandar de QStyle mezclados con botones de texto. Aqui:

- apply_theme(): "dark"/"light" usan Fusion con una paleta explicita
  (igual en Windows 10 y 11); "system" sigue el modo del sistema: en modo
  claro el estilo nativo, en modo oscuro la misma paleta oscura que "dark"
  (el estilo nativo dejaba texto blanco sobre su paleta clara).
- make_icon(): iconos SVG propios (dibujados para este proyecto, sin
  licencias de terceros), tenidos con el color de texto de la paleta
  activa. Se renderizan con QSvgRenderer (QtSvg), no con el plugin de
  formatos de imagen, para no depender de que el empaquetado lo incluya.
"""

import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

THEME_LABELS = {"system": "Sistema", "dark": "Oscuro", "light": "Claro"}

# -- colores de las superpuestas sobre el video (iguales en todo tema) ------
OSD_STYLE = (
    "background-color: rgba(0, 0, 0, 170); color: white; padding: 6px 16px;"
    "border-radius: 8px; font-size: 13pt;"
)
# Estadisticas (4.14): texto chico y monoespaciado, alineado a la izquierda.
STATS_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 180); color: white; padding: 8px 12px;"
    "border-radius: 6px; font-family: Consolas, 'Courier New', monospace; font-size: 9pt;"
)
PREVIEW_POPUP_STYLE = "background-color: black; border: 1px solid #888888;"
PREVIEW_TIME_STYLE = "color: white; font-size: 9pt;"
FULLSCREEN_CONTROLLER_STYLE = (
    "#fullscreenController { background-color: rgba(18, 18, 18, 215); border-radius: 10px; }"
    "#fullscreenController QLabel { color: white; }"
    "#fullscreenController QToolButton { color: white; border: none; padding: 4px; }"
    "#fullscreenController QToolButton:hover { background-color: rgba(255, 255, 255, 40); border-radius: 6px; }"
)
FULLSCREEN_ICON_COLOR = "#ffffff"
LIVE_LABEL = "EN VIVO"

LOOP_MARKER_COLOR = QColor("#ff8c3c")
BOOKMARK_MARKER_COLOR = QColor("#ffd23c")
CHAPTER_MARKER_COLOR = QColor("#6ab0ff")
# Tramo ya almacenado de un stream de red (PositionSlider.set_buffered_range):
# translucido para que se vea sobre la ranura clara u oscura.
BUFFERED_RANGE_COLOR = QColor(128, 160, 255, 110)

DARK_COLORS = {
    "window": "#1e1e1e",
    "base": "#252526",
    "alternate": "#2d2d30",
    "text": "#e6e6e6",
    "disabled_text": "#7a7a7a",
    "button": "#2d2d30",
    "highlight": "#3d7eff",
    "highlighted_text": "#ffffff",
    "link": "#6ab0ff",
    "tooltip_base": "#2d2d30",
}

_original = {"style": None}


def dark_palette() -> QPalette:
    c = {k: QColor(v) for k, v in DARK_COLORS.items()}
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, c["window"])
    p.setColor(QPalette.ColorRole.WindowText, c["text"])
    p.setColor(QPalette.ColorRole.Base, c["base"])
    p.setColor(QPalette.ColorRole.AlternateBase, c["alternate"])
    p.setColor(QPalette.ColorRole.ToolTipBase, c["tooltip_base"])
    p.setColor(QPalette.ColorRole.ToolTipText, c["text"])
    p.setColor(QPalette.ColorRole.PlaceholderText, c["disabled_text"])
    p.setColor(QPalette.ColorRole.Text, c["text"])
    p.setColor(QPalette.ColorRole.Button, c["button"])
    p.setColor(QPalette.ColorRole.ButtonText, c["text"])
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ff5555"))
    p.setColor(QPalette.ColorRole.Link, c["link"])
    p.setColor(QPalette.ColorRole.Highlight, c["highlight"])
    p.setColor(QPalette.ColorRole.HighlightedText, c["highlighted_text"])
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c["disabled_text"])
    return p


def _set_color_scheme(app, scheme):
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt >= 6.8
        hints.setColorScheme(scheme)


def apply_theme(app, theme: str) -> str:
    """Aplica el tema a toda la aplicacion; devuelve el tema efectivo."""
    if app is None:
        return theme
    if _original["style"] is None:
        _original["style"] = app.style().name()
    if theme == "dark":
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
        _set_color_scheme(app, Qt.ColorScheme.Dark)
    elif theme == "light":
        app.setStyle("Fusion")
        _set_color_scheme(app, Qt.ColorScheme.Light)
        app.setPalette(app.style().standardPalette())
    else:
        theme = "system"
        _set_color_scheme(app, Qt.ColorScheme.Unknown)
        if system_is_dark(app):
            # The native Windows style keeps white menu text in dark mode while its standard
            # palette is the light one: white on light grey (UI1). Dark mode gets the same
            # explicit dark palette as "Oscuro".
            app.setStyle("Fusion")
            app.setPalette(dark_palette())
        else:
            app.setStyle(_original["style"] or "Fusion")
            app.setPalette(app.style().standardPalette())
    return theme


def system_is_dark(app) -> bool:
    """Whether the operating system is in dark mode (Qt's colour scheme; unknown counts as light)."""
    hints = app.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def icon_color(widget=None) -> str:
    palette = widget.palette() if widget is not None else QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.ButtonText).name()


# -- iconos (viewBox 24x24; "{c}" = color) --------------------------------
_STROKE = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
ICONS = {
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="{c}"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="{c}"/>'
             '<rect x="14" y="4.5" width="4" height="15" rx="1" fill="{c}"/>',
    "stop": '<rect x="5.5" y="5.5" width="13" height="13" rx="1.5" fill="{c}"/>',
    "previous": '<rect x="4.5" y="5" width="2.5" height="14" rx="1" fill="{c}"/>'
                '<path d="M19.5 5v14L8.5 12z" fill="{c}"/>',
    "next": '<rect x="17" y="5" width="2.5" height="14" rx="1" fill="{c}"/>'
            '<path d="M4.5 5v14l11-7z" fill="{c}"/>',
    "volume": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="{c}"/>'
              f'<path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" {_STROKE}/>',
    "muted": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="{c}"/>'
             f'<path d="M15.5 9.5l5 5M20.5 9.5l-5 5" {_STROKE}/>',
    "fullscreen": f'<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" {_STROKE}/>',
    "fullscreen_exit": f'<path d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5" {_STROKE}/>',
    "shuffle": f'<path d="M3.5 7h3.5c4.5 0 5.5 10 10 10h3.5M3.5 17h3.5c1.8 0 3-1.6 4-3.5'
               f'M13 10c1-1.7 2.2-3 4-3h3.5M18 4.5l2.5 2.5-2.5 2.5M18 14.5l2.5 2.5-2.5 2.5" {_STROKE}/>',
    "repeat": f'<path d="M4.5 11V9.5a2.5 2.5 0 0 1 2.5-2.5h12.5M17 4.5l2.5 2.5L17 9.5'
              f'M19.5 13v1.5a2.5 2.5 0 0 1-2.5 2.5H4.5M7 19.5L4.5 17 7 14.5" {_STROKE}/>',
    "repeat_one": f'<path d="M4.5 11V9.5a2.5 2.5 0 0 1 2.5-2.5h12.5M17 4.5l2.5 2.5L17 9.5'
                  f'M19.5 13v1.5a2.5 2.5 0 0 1-2.5 2.5H4.5M7 19.5L4.5 17 7 14.5" {_STROKE}/>'
                  '<path d="M11 10.5l1.5-1v5" fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round"/>',
    "ab_loop": f'<path d="M4 6v12M20 6v12" {_STROKE}/>'
               '<text x="12" y="15.5" font-size="8.5" font-family="Arial" font-weight="bold" '
               'text-anchor="middle" fill="{c}">A-B</text>',
}


def svg_markup(name: str, color: str) -> str:
    body = ICONS[name].replace("{c}", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def render_icon_pixmap(name: str, color: str, size: int = 24, dpr: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode("utf-8")))
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def taskbar_icon_color() -> str:
    """Color de los iconos de la miniatura de la barra de tareas: el tema de Windows
    (no el de la app), porque la miniatura usa el fondo de la barra de tareas."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                if winreg.QueryValueEx(key, "SystemUsesLightTheme")[0]:
                    return "#202020"
        except OSError:
            pass
    return "#FFFFFF"


def make_icon(name: str, color: str) -> QIcon:
    icon = QIcon()
    for dpr in (1.0, 2.0):
        icon.addPixmap(render_icon_pixmap(name, color, 24, dpr))
    return icon
