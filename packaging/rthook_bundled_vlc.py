# Runtime hook de PyInstaller: usa el libVLC incluido en el paquete (si se
# construyo con BUNDLE_VLC=1); si no lo hay, el VLC instalado en el sistema.
import sys

from player.vlc_check import configure_bundled_vlc

configure_bundled_vlc(getattr(sys, "_MEIPASS", None))
