# Empaquetado (PyInstaller)

## Goal

Generar un `.exe` de Windows de un solo archivo que no necesite tener
Python instalado, para poder distribuirlo o abrirlo con doble clic.

## Build

```bash
pip install -r requirements-build.txt
pyinstaller ReproductorMultimediaPro.spec
```

El resultado queda en:

```text
dist/ReproductorMultimediaPro.exe
```

`ReproductorMultimediaPro.spec` construye desde `run.py`, con
`console=False` (sin ventana de consola, igual que `run.pyw`) y un icono
por defecto de PyInstaller. **No empaqueta VLC**: `libvlc.dll` varía por
versión/arquitectura y VLC ya se instala y actualiza por su cuenta, así
que la máquina que ejecute el `.exe` sigue necesitando VLC media player
instalado aparte (ver "Known Issues" en `docs/PROJECT_STATUS.md`).

El build completo (análisis de dependencias de PySide6 incluido) tarda
alrededor de un minuto. Si lo corres en segundo plano, revisa el log en
vez de asumir que terminó apenas el proceso deja de aparecer en la lista
de tareas — PyInstaller puede tener procesos hijos con otro PID.

## Verificar el ejecutable

No hay una suite automatizada contra el `.exe` en sí (los tests corren
contra el código fuente). Verificación manual recomendada después de cada
build:

```bash
dist/ReproductorMultimediaPro.exe ruta/a/un/audio.mp3 ruta/a/un/video.mp4
```

Confirmar que:
1. Abre sin errores ni diálogos inesperados.
2. Reproduce el primer archivo y el título de la ventana lo refleja.
3. Al terminar, avanza automáticamente al segundo.

Esto ejercita en un solo paso tanto la normalización de rutas como la
recreación de instancia del visualizador (ver "Recently Fixed" en
`docs/PROJECT_STATUS.md`) dentro del binario empaquetado, no solo en el
código fuente.

## Distribución

`build/` y `dist/` están en `.gitignore` — el `.exe` es un artefacto local,
no se sube al repositorio. Para distribuirlo, comparte el archivo
`ReproductorMultimediaPro.exe` directamente (es de un solo archivo) junto
con la indicación de instalar VLC media player si el destinatario no lo
tiene.
