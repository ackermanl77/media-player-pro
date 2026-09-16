import sys

from PySide6.QtWidgets import QApplication, QMessageBox


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Reproductor Multimedia Pro")

    try:
        from player.main_window import MainWindow
    except OSError:
        # python-vlc no pudo cargar libvlc: VLC media player no está
        # instalado en el sistema (o no coincide la arquitectura de 32/64
        # bits con la de este Python). Sin este mensaje, la app terminaba
        # con un traceback de ctypes ininteligible para el usuario.
        QMessageBox.critical(
            None,
            "VLC no encontrado",
            "No se encontró la librería de VLC (libvlc).\n\n"
            "Instala VLC media player desde https://www.videolan.org/vlc/\n"
            "(usa la versión de 64 bits si tu Python es de 64 bits) "
            "y vuelve a abrir esta aplicación.",
        )
        sys.exit(1)

    window = MainWindow()
    window.resize(1150, 720)
    window.show()

    files = sys.argv[1:]
    if files:
        window.add_files_to_playlist(files)
        window.play_index(0)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
