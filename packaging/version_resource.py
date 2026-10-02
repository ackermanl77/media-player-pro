"""Recurso de version de Windows (pestana Detalles del .exe) generado desde
player.__version__, la unica fuente de la version del proyecto (tambien la
leen pyproject.toml, el instalador y el workflow de release).

Lo usa ReproductorMultimediaPro.spec. Las funciones de texto no necesitan
PyInstaller (se prueban en tests/test_version.py); build_version_info() si.
"""

import ast
import os
import re

APP_NAME = "Reproductor Multimedia Pro"
EXE_NAME = "ReproductorMultimediaPro"
COMPANY = "MELEJ"
# Espanol (0x0C0A, Espana alfabetizacion internacional) + Unicode (1200).
LANGUAGE_ID = 0x0C0A
CODEPAGE = 1200


def read_version(project_root: str) -> str:
    """__version__ de player/__init__.py, sin importar el paquete."""
    path = os.path.join(project_root, "player", "__init__.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"No hay __version__ en {path}")


def version_tuple(version: str) -> tuple:
    """Cuatro numeros de 16 bits, como los guarda Windows: "1.2.3" ->
    (1, 2, 3, 0); "1.2.3rc1" -> (1, 2, 3, 0)."""
    numbers = []
    for part in version.split(".")[:4]:
        match = re.match(r"\d+", part)
        numbers.append(min(int(match.group()), 0xFFFF) if match else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def version_strings(version: str) -> dict:
    """Tabla de textos del recurso (lo que muestra Propiedades -> Detalles)."""
    return {
        "CompanyName": COMPANY,
        "FileDescription": APP_NAME,
        "FileVersion": version,
        "InternalName": EXE_NAME,
        "LegalCopyright": f"© {COMPANY}",
        "OriginalFilename": f"{EXE_NAME}.exe",
        "ProductName": APP_NAME,
        "ProductVersion": version,
    }


def build_version_info(version: str):
    """VSVersionInfo para EXE(version=...) de PyInstaller."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = version_tuple(version)
    table_id = f"{LANGUAGE_ID:04x}{CODEPAGE:04x}"
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,  # VOS_NT_WINDOWS32
            fileType=0x1,  # VFT_APP
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(table_id, [StringStruct(k, v) for k, v in version_strings(version).items()]),
            ]),
            VarFileInfo([VarStruct("Translation", [LANGUAGE_ID, CODEPAGE])]),
        ],
    )
