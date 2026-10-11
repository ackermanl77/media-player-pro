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
