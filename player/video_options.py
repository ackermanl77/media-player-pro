"""Opciones de los submenus Video -> Relacion de aspecto / Recortar /
Desentrelazado (modulo puro, sin Qt ni VLC). Las teclas A y C recorren las
dos primeras listas, como en VLC."""

# (etiqueta, valor que entiende libVLC); "" = el del video / sin recorte.
ASPECT_RATIOS = [
    ("Predeterminada", ""), ("16:9", "16:9"), ("4:3", "4:3"), ("1:1", "1:1"), ("16:10", "16:10"),
    ("2,21:1", "221:100"), ("2,35:1", "235:100"), ("2,39:1", "239:100"), ("5:4", "5:4"),
]
CROP_RATIOS = [
    ("Ninguno", ""), ("16:9", "16:9"), ("4:3", "4:3"), ("1:1", "1:1"), ("16:10", "16:10"),
    ("1,85:1", "185:100"), ("2,21:1", "221:100"), ("2,35:1", "235:100"), ("2,39:1", "239:100"), ("5:4", "5:4"),
]
# Video -> Rotar / voltear (4.13): valores de --transform-type del filtro transform de libVLC.
ROTATIONS = [
    ("Sin rotar", ""), ("90° a la derecha", "90"), ("180°", "180"), ("90° a la izquierda", "270"),
    ("Voltear horizontalmente", "hflip"), ("Voltear verticalmente", "vflip"),
]
# Video > Filtros (4.17): filtros de video de libVLC, en este orden en la cadena
# --video-filter (despues de transform). Se pueden combinar.
VIDEO_FILTERS = [
    ("Enfocar", "sharpen"),
    ("Reducir ruido", "hqdn3d"),
    ("Suavizar bandas de color", "gradfun"),
    ("Quitar bloques (posprocesado)", "postproc"),
]
VIDEO_FILTER_VALUES = tuple(value for _label, value in VIDEO_FILTERS)
# Audio > Efectos (3.17): filtros de audio de libVLC, combinables, en este orden.
AUDIO_EFFECTS = [
    ("Modo nocturno (compresor)", "compressor"),
    ("Ampliar estéreo", "stereo_widen"),
    ("Auriculares: sonido envolvente virtual", "headphone_channel_mixer"),
]
AUDIO_EFFECT_VALUES = tuple(value for _label, value in AUDIO_EFFECTS)
# Tono (scaletempo_pitch), en semitonos; 0 = sin cambio.
PITCH_STEPS = (-6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6)
MIN_PITCH, MAX_PITCH = -12.0, 12.0


def format_pitch(semitones: float) -> str:
    if not semitones:
        return "Original"
    sign = "+" if semitones > 0 else "−"
    value = abs(semitones)
    text = f"{value:g}"
    return f"{sign}{text} semitono{'s' if value != 1 else ''}"


DEINTERLACE_LABELS = [
    ("Automático", "auto"), ("Desactivado", "off"), ("Blend", "blend"), ("Bob", "bob"), ("Lineal", "linear"),
    ("X", "x"), ("Yadif", "yadif"), ("Yadif (2x)", "yadif2x"),
]


def choice_label(choices, value) -> str:
    return next((label for label, v in choices if v == value), str(value))


def next_choice(choices, current):
    """El valor que sigue a `current` (vuelve al primero al final, o si
    `current` no esta en la lista)."""
    values = [v for _label, v in choices]
    if current not in values:
        return values[0]
    return values[(values.index(current) + 1) % len(values)]
