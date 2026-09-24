"""Orden de reproduccion de la playlist (secuencial o aleatorio) y reglas
de "siguiente"/"anterior". Modulo puro, sin VLC ni Qt: MainWindow solo le
avisa de cambios en la lista (agregar/quitar/mover) y le pregunta que
indice sigue.

Aleatorio funciona como en la mayoria de reproductores: al activarlo se
baraja una vez la lista (sin reemplazo), asi cada pista suena una sola vez
por vuelta; "Anterior" recorre el historial real de lo que sono (no la
pista de indice - 1); con Repetir: No la reproduccion termina cuando se
agota la vuelta, con Repetir: Todo se baraja una vuelta nueva.
"""

import random


class PlaylistOrder:
    def __init__(self, count: int = 0, rng=None):
        self._rng = rng or random.Random()
        self._count = count
        self._current = -1
        self._shuffle = False
        self._history = []   # pistas que ya sonaron (aleatorio), la ultima al final
        self._upcoming = []  # pistas que faltan en esta vuelta (aleatorio)

    # -- estado -------------------------------------------------------------
    @property
    def count(self) -> int:
        return self._count

    @property
    def current(self) -> int:
        return self._current

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    def upcoming(self) -> list:
        return list(self._upcoming)

    def history(self) -> list:
        return list(self._history)

    def set_shuffle(self, enabled: bool):
        self._shuffle = enabled
        self._history = []
        self._upcoming = []
        if enabled:
            self._upcoming = [i for i in range(self._count) if i != self._current]
            self._rng.shuffle(self._upcoming)

    # -- navegacion ---------------------------------------------------------
    def jump_to(self, index: int):
        """El usuario (o advance/back) eligio esta pista. En aleatorio, la
        actual pasa al historial y la elegida sale de las pendientes, para
        no repetirla en esta vuelta."""
        if index == self._current:
            return
        if self._shuffle:
            if self._current != -1:
                self._history.append(self._current)
            if index in self._upcoming:
                self._upcoming.remove(index)
        self._current = index

    def advance(self, repeat_all: bool):
        """Indice de la siguiente pista (y la marca como actual), o None si
        la lista termino (sin Repetir: Todo)."""
        if self._count == 0:
            return None
        if not self._shuffle:
            nxt = self._current + 1
            if nxt >= self._count:
                if not repeat_all:
                    return None
                nxt = 0
            self._current = nxt
            return nxt
        if not self._upcoming:
            if not repeat_all:
                return None
            self._upcoming = list(range(self._count))
            self._rng.shuffle(self._upcoming)
            # Que la vuelta nueva no empiece repitiendo la que acaba de sonar.
            if self._count > 1 and self._upcoming[0] == self._current:
                swap = self._rng.randrange(1, self._count)
                self._upcoming[0], self._upcoming[swap] = self._upcoming[swap], self._upcoming[0]
        nxt = self._upcoming[0]
        if nxt == self._current:
            # Lista de una sola pista con Repetir: Todo.
            self._upcoming.pop(0)
            return nxt
        self.jump_to(nxt)
        return nxt

    def back(self, repeat_all: bool):
        """Indice de la pista anterior (y la marca como actual), o None si no
        hay anterior (el llamador reinicia la actual)."""
        if self._count == 0:
            return None
        if not self._shuffle:
            prev = self._current - 1
            if prev < 0:
                if not repeat_all or self._current == -1:
                    return None
                prev = self._count - 1
            self._current = prev
            return prev
        if not self._history:
            return None
        prev = self._history.pop()
        if self._current != -1:
            self._upcoming.insert(0, self._current)
        self._current = prev
        return prev

    # -- cambios en la lista --------------------------------------------------
    def reset(self, count: int = 0):
        self._count = count
        self._current = -1
        self.set_shuffle(self._shuffle)

    def append(self, n: int):
        """Se agregaron n pistas al final. En aleatorio, se intercalan al
        azar entre las pendientes de esta vuelta."""
        new = list(range(self._count, self._count + n))
        self._count += n
        if self._shuffle:
            for index in new:
                self._upcoming.insert(self._rng.randint(0, len(self._upcoming)), index)

    def remove(self, rows):
        """Se quitaron estas filas (indices previos al borrado). Si la actual
        estaba entre ellas, current pasa a -1."""
        removed = set(rows)
        if not removed:
            return
        remap = {}
        shift = 0
        for i in range(self._count):
            if i in removed:
                shift += 1
            else:
                remap[i] = i - shift
        self._count -= len(removed & set(range(self._count)))
        self._current = remap.get(self._current, -1)
        self._history = self._dedupe_adjacent([remap[i] for i in self._history if i in remap])
        self._upcoming = [remap[i] for i in self._upcoming if i in remap]

    def move(self, src: int, dst: int):
        """Se movio la fila src a la posicion dst (semantica de list.insert
        tras list.pop). El orden aleatorio sigue apuntando a las mismas
        pistas, solo cambian sus indices."""
        if src == dst or not (0 <= src < self._count and 0 <= dst < self._count):
            return
        order = list(range(self._count))
        order.insert(dst, order.pop(src))
        remap = {old: new for new, old in enumerate(order)}
        if self._current != -1:
            self._current = remap[self._current]
        self._history = [remap[i] for i in self._history]
        self._upcoming = [remap[i] for i in self._upcoming]

    @staticmethod
    def _dedupe_adjacent(items: list) -> list:
        result = []
        for i in items:
            if not result or result[-1] != i:
                result.append(i)
        return result


def playback_failed(error_seen: bool, state_is_error: bool, state_is_ended: bool,
                    length_ms: int, max_time_ms: int) -> bool:
    """Decide si una pista "termino" porque no se pudo reproducir. Verificado
    contra libVLC 3.0.23 en Windows: un archivo inexistente o corrupto casi
    nunca deja get_state() en State.Error -- pasa directo a State.Ended
    (el inexistente dispara el evento MediaPlayerEncounteredError; el
    corrupto ni eso: llega a Playing un instante con largo 0). Asi que
    tambien cuenta como fallo un Ended sin largo conocido y sin haber
    avanzado nunca el tiempo (un stream que si sono avanza el tiempo aunque
    su largo sea 0). Solo aplica una vez que la pista termino (Error/Ended)."""
    if not (state_is_error or state_is_ended):
        return False
    if error_seen or state_is_error:
        return True
    return state_is_ended and length_ms <= 0 and max_time_ms <= 0
