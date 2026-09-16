# -*- mode: python ; coding: utf-8 -*-
#
# Genera un ejecutable de Windows con PyInstaller. No empaqueta VLC: la app
# sigue necesitando VLC media player instalado en la maquina destino (ver
# README.md), porque libvlc.dll varia por version/arquitectura y VLC ya lo
# distribuye e instala por su cuenta.

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ["player.backend", "player.main_window", "player.formats"]
hiddenimports += collect_submodules("player")

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ReproductorMultimediaPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
