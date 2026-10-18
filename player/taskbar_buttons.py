"""Botones de la miniatura de la barra de tareas (4.12): Anterior,
Reproducir/Pausar y Siguiente bajo la vista previa que Windows muestra al pasar
el mouse por el boton del programa, como en VLC o Windows Media Player.

Es ITaskbarList3 (ThumbBarAddButtons/ThumbBarUpdateButtons) por ctypes, sin
dependencias: Qt 6 ya no trae QWinThumbnailToolBar. Los botones solo se pueden
agregar cuando Windows creo el boton de la barra de tareas (mensaje registrado
"TaskbarButtonCreated", que tambien llega si Explorer se reinicia), y un clic
llega a la ventana como WM_COMMAND con THBN_CLICKED en la palabra alta de
wParam: MainWindow.nativeEvent() le pasa cada mensaje a handle_message().

Fuera de Windows, o si COM falla, available es False y no hace nada."""

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QSize, Signal

log = logging.getLogger(__name__)

WM_COMMAND = 0x0111
THBN_CLICKED = 0x1800
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
THBF_ENABLED, THBF_DISABLED = 0x0, 0x1
# (id del boton, comando de MainWindow.media_command)
BUTTONS = ((1, "previous"), (2, "toggle"), (3, "next"))
_COMMANDS = dict(BUTTONS)
ICON_SIZE = 16

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
_IID_ITASKBAR_LIST3 = "{ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf}"
# Posiciones en la vtable de ITaskbarList3 (IUnknown 0-2, ITaskbarList 3-7, ITaskbarList2 8).
_VT_RELEASE, _VT_HRINIT, _VT_ADD_BUTTONS, _VT_UPDATE_BUTTONS = 2, 3, 15, 16


class THUMBBUTTON(ctypes.Structure):
    _fields_ = [
        ("dwMask", wintypes.DWORD),
        ("iId", wintypes.UINT),
        ("iBitmap", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 260),
        ("dwFlags", wintypes.DWORD),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def command_for_message(msg: int, wparam: int, button_created_msg: int) -> str:
    """"created" para TaskbarButtonCreated, el comando de un clic en un boton
    ("previous"/"toggle"/"next"), o "" si el mensaje no es de la barra de tareas."""
    if button_created_msg and msg == button_created_msg:
        return "created"
    if msg == WM_COMMAND and (wparam >> 16) & 0xFFFF == THBN_CLICKED:
        return _COMMANDS.get(wparam & 0xFFFF, "")
    return ""


def buttons_struct(playing: bool, enabled: bool, icons: dict) -> "ctypes.Array":
    """El arreglo de THUMBBUTTON para ThumbBarAdd/UpdateButtons. `icons` va de
    nombre de icono ("previous", "play", "pause", "next") a HICON."""
    array = (THUMBBUTTON * len(BUTTONS))()
    tips = {"previous": "Pista anterior", "toggle": "Pausar" if playing else "Reproducir", "next": "Pista siguiente"}
    for slot, (button_id, command) in zip(array, BUTTONS):
        icon_name = ("pause" if playing else "play") if command == "toggle" else command
        slot.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
        slot.iId = button_id
        slot.hIcon = icons.get(icon_name) or 0
        slot.szTip = tips[command]
        slot.dwFlags = THBF_ENABLED if enabled else THBF_DISABLED
    return array


class TaskbarButtons(QObject):
    pressed = Signal(str)

    def __init__(self, icon_factory=None, parent=None):
        """icon_factory(nombre) -> QIcon; se llama una vez por icono al crear los botones."""
        super().__init__(parent)
        self._icon_factory = icon_factory
        self._taskbar = None
        self._hwnd = 0
        self._added = False
        self._icons: dict = {}
        self._state = (False, False)  # (reproduciendo, hay algo cargado)
        self._button_created_msg = 0
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            user32.RegisterWindowMessageW.restype = wintypes.UINT
            self._button_created_msg = user32.RegisterWindowMessageW("TaskbarButtonCreated")
            # Qt corre como proceso con privilegios normales; si alguna vez corriera elevado,
            # Explorer no podria mandarle estos mensajes sin esto.
            user32.ChangeWindowMessageFilter(self._button_created_msg, 1)
            user32.ChangeWindowMessageFilter(WM_COMMAND, 1)
            self._taskbar = self._create_taskbar_list()
        except (OSError, AttributeError) as exc:
            log.info("Botones de la barra de tareas no disponibles: %s", exc)
            self._taskbar = None

    @property
    def available(self) -> bool:
        return self._taskbar is not None

    # -- COM --------------------------------------------------------------
    @staticmethod
    def _guid(text: str) -> _GUID:
        guid = _GUID()
        if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid)) != 0:
            raise OSError(f"GUID invalido: {text}")
        return guid

    def _create_taskbar_list(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)  # Qt ya inicializo COM en este hilo: S_FALSE, sin efecto
        pointer = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(self._guid(_CLSID_TASKBAR_LIST)), None, 1,  # CLSCTX_INPROC_SERVER
                                    ctypes.byref(self._guid(_IID_ITASKBAR_LIST3)), ctypes.byref(pointer))
        if hr != 0 or not pointer.value:
            raise OSError(f"CoCreateInstance(TaskbarList) fallo: {hr & 0xFFFFFFFF:#x}")
        if self._call(pointer.value, _VT_HRINIT, []) != 0:
            raise OSError("ITaskbarList3::HrInit fallo")
        return pointer.value

    @staticmethod
    def _call(this, index: int, args: list, argtypes=()):
        vtable = ctypes.cast(ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])(this, *args)

    # -- ventana ----------------------------------------------------------
    def attach(self, hwnd: int) -> None:
        self._hwnd = int(hwnd)

    def handle_message(self, msg: int, wparam: int) -> bool:
        """Para MainWindow.nativeEvent(): True si el mensaje era un clic en un boton."""
        if not self.available:
            return False
        command = command_for_message(msg, wparam, self._button_created_msg)
        if command == "created":
            self._added = False  # Explorer se reinicio (o es la primera vez): agregarlos de nuevo
            self._add_buttons()
            return False
        if command:
            self.pressed.emit(command)
            return True
        return False

    def set_state(self, playing: bool, has_media: bool) -> None:
        if (playing, has_media) == self._state:
            return
        self._state = (playing, has_media)
        if self._added:
            self._update(_VT_UPDATE_BUTTONS)

    def _hicon(self, name: str) -> int:
        if name not in self._icons:
            handle = 0
            if self._icon_factory is not None:
                image = self._icon_factory(name).pixmap(QSize(ICON_SIZE, ICON_SIZE)).toImage()
                handle = int(image.toHICON()) if not image.isNull() else 0
            self._icons[name] = handle
        return self._icons[name]

    def _update(self, method: int) -> bool:
        if not self.available or not self._hwnd:
            return False
        icons = {name: self._hicon(name) for name in ("previous", "play", "pause", "next")}
        array = buttons_struct(*self._state, icons)
        hr = self._call(self._taskbar, method, [wintypes.HWND(self._hwnd), wintypes.UINT(len(array)), array],
                        (wintypes.HWND, wintypes.UINT, ctypes.POINTER(THUMBBUTTON)))
        if hr != 0:
            log.info("ThumbBar%sButtons fallo: %#x", "Add" if method == _VT_ADD_BUTTONS else "Update",
                     hr & 0xFFFFFFFF)
        return hr == 0

    def _add_buttons(self) -> None:
        # ThumbBarAddButtons solo se puede llamar una vez por ventana; despues se actualizan.
        self._added = self._update(_VT_ADD_BUTTONS) or self._update(_VT_UPDATE_BUTTONS)

    @property
    def buttons_added(self) -> bool:
        return self._added

    def close(self) -> None:
        for handle in self._icons.values():
            if handle:
                ctypes.windll.user32.DestroyIcon(wintypes.HICON(handle))
        self._icons.clear()
        if self._taskbar is not None:
            self._call(self._taskbar, _VT_RELEASE, [])
            self._taskbar = None
