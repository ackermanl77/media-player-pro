"""`ReproductorMultimediaPro.exe --self-test [--self-test-output=ARCHIVO]`:
comprueba que el ejecutable empaquetado arranca de verdad -- modulos, Qt,
traduccion, libVLC (y sus plugins: reproduce un WAV generado) y la ventana
principal construida con la plataforma "offscreen" -- sin tocar los ajustes
ni la lista del usuario. Escribe una linea por comprobacion ("ok"/"FALLA")
en ARCHIVO (el .exe no tiene consola) o en la salida estandar, y termina con
codigo 0 si todo paso. Lo usa el workflow de release despues de construir."""

import os
import sys
import tempfile
import time
import traceback
import wave

SELF_TEST_FLAG = "--self-test"
OUTPUT_PREFIX = "--self-test-output="


def wants_self_test(argv) -> bool:
    return SELF_TEST_FLAG in argv


def output_path(argv):
    for arg in argv:
        if arg.startswith(OUTPUT_PREFIX):
            return arg[len(OUTPUT_PREFIX):] or None
    return None


def _silent_wav(path: str, seconds: float = 2.0) -> str:
    with wave.open(path, "w") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(b"\x00\x00\x00\x00" * int(44100 * seconds))
    return path


def run_checks(workdir: str) -> list:
    """[(nombre, ok, detalle)]; cada comprobacion atrapa sus propios errores."""
    results = []

    def check(name, func):
        try:
            detail = func()
            results.append((name, True, detail or ""))
            return True
        except Exception as exc:  # noqa: BLE001 -- se informa, no se propaga
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
            if sys.stderr is not None:
                traceback.print_exc(file=sys.stderr)
            return False

    def version():
        from player import __version__

        return f"{__version__}, Python {sys.version.split()[0]}"

    check("version", version)

    app_holder = {}

    def qt():
        from PySide6 import __version__ as pyside_version
        from PySide6.QtWidgets import QApplication

        app_holder["app"] = QApplication.instance() or QApplication([sys.argv[0], "-platform", "offscreen"])
        return f"PySide6 {pyside_version}, plataforma {app_holder['app'].platformName()}"

    if not check("qt", qt):
        return results

    def translation():
        # Lo mismo que run.install_spanish_translator (run.py es __main__ en el .exe).
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if not QTranslator().load(QLocale(QLocale.Language.Spanish), "qtbase", "_", path):
            raise RuntimeError(f"no se encontro qtbase_es.qm en {path}")
        return "qtbase_es.qm"

    check("traduccion", translation)

    def libvlc():
        import vlc

        from player.vlc_check import version_warning

        version = vlc.libvlc_get_version().decode("utf-8", "replace")
        warning = version_warning(version)
        if warning:
            raise RuntimeError(warning)
        return f"libVLC {version}, python-vlc {getattr(vlc, '__version__', '?')}"

    if not check("libvlc", libvlc):
        return results

    def playback():
        from player import backend
        from player.vlc_internals import audio_filters_supported

        backend.BASE_VLC_ARGS = backend.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
        player = backend.VLCPlayer()
        try:
            player.load(_silent_wav(os.path.join(workdir, "self-test.wav")))
            player.play()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and player.playback_state() != backend.PlaybackState.PLAYING:
                time.sleep(0.05)
            if player.playback_state() != backend.PlaybackState.PLAYING:
                raise RuntimeError(f"el WAV no llego a reproducirse ({player.playback_state().name})")
            details = player.media_details()
            audio = [t for t in details["tracks"] if t["type"] == "audio"]
            if not audio or audio[0].get("rate") != 44100:
                raise RuntimeError(f"pistas inesperadas: {details['tracks']}")
            return f"WAV reproducido; normalizador {'disponible' if audio_filters_supported() else 'no disponible'}"
        finally:
            player.close()

    check("reproduccion", playback)

    def main_window():
        from player.main_window import MainWindow

        window = MainWindow()
        try:
            menus = [a.text() for a in window.menuBar().actions()]
            if len(menus) < 5:
                raise RuntimeError(f"menus: {menus}")
            return f"{len(menus)} menus, {len(window.action_registry.ids())} acciones"
        finally:
            window.close()

    check("ventana", main_window)
    return results


def main(argv) -> int:
    target = output_path(argv)
    saved = {key: os.environ.get(key) for key in ("USERPROFILE", "HOME", "LOCALAPPDATA")}
    with tempfile.TemporaryDirectory(prefix="rmp-self-test-", ignore_cleanup_errors=True) as workdir:
        # Ajustes, sesion y registros en una carpeta temporal: la prueba no
        # toca los del usuario (Path.home() lee USERPROFILE/HOME en cada llamada).
        for key in saved:
            os.environ[key] = workdir
        try:
            results = run_checks(workdir)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    lines = [f"{'ok   ' if ok else 'FALLA'} {name}: {detail}" for name, ok, detail in results]
    passed = bool(results) and all(ok for _name, ok, _detail in results)
    lines.append("RESULTADO: " + ("todo bien" if passed else "hay fallas"))
    text = "\n".join(lines) + "\n"
    if target:
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
    elif sys.stdout is not None:
        sys.stdout.write(text)
    return 0 if passed else 1
