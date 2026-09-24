import random

from player.playlist_order import PlaylistOrder, playback_failed


def _drain(order, repeat_all=False, limit=100):
    played = []
    for _ in range(limit):
        nxt = order.advance(repeat_all)
        if nxt is None:
            break
        played.append(nxt)
    return played


# ------------------------------------------------------------ secuencial
def test_sequential_advances_in_order_and_ends_without_repeat():
    order = PlaylistOrder(3)
    assert _drain(order) == [0, 1, 2]
    assert order.advance(repeat_all=False) is None


def test_sequential_wraps_with_repeat_all():
    order = PlaylistOrder(2)
    order.jump_to(1)
    assert order.advance(repeat_all=True) == 0


def test_sequential_back_stops_at_start_unless_repeat_all():
    order = PlaylistOrder(3)
    order.jump_to(0)
    assert order.back(repeat_all=False) is None
    assert order.back(repeat_all=True) == 2


# -------------------------------------------------------------- aleatorio
def test_shuffle_plays_each_track_once_then_ends_with_repeat_none():
    order = PlaylistOrder(10, rng=random.Random(1))
    order.jump_to(3)
    order.set_shuffle(True)
    played = [3] + _drain(order)
    assert sorted(played) == list(range(10))  # sin reemplazo: cada una una vez
    assert order.advance(repeat_all=False) is None


def test_shuffle_with_repeat_all_reshuffles_without_immediate_repeat():
    for seed in range(30):
        order = PlaylistOrder(3, rng=random.Random(seed))
        order.set_shuffle(True)
        played = _drain(order, repeat_all=True, limit=30)
        assert len(played) == 30
        assert all(a != b for a, b in zip(played, played[1:]))
        for start in range(0, 30, 3):
            assert sorted(played[start:start + 3]) == [0, 1, 2]


def test_shuffle_single_track_repeat_all_keeps_playing_it():
    order = PlaylistOrder(1, rng=random.Random(0))
    order.set_shuffle(True)
    assert _drain(order, repeat_all=True, limit=3) == [0, 0, 0]


def test_shuffle_previous_walks_the_real_history():
    order = PlaylistOrder(6, rng=random.Random(7))
    order.set_shuffle(True)
    played = _drain(order, limit=4)
    assert order.back(repeat_all=False) == played[2]
    assert order.back(repeat_all=False) == played[1]
    # Y "Siguiente" vuelve a avanzar por el mismo camino.
    assert order.advance(repeat_all=False) == played[2]
    assert order.advance(repeat_all=False) == played[3]


def test_shuffle_previous_at_the_start_of_history_returns_none():
    order = PlaylistOrder(4, rng=random.Random(0))
    order.set_shuffle(True)
    order.advance(False)
    assert order.back(repeat_all=True) is None


def test_user_jump_in_shuffle_is_not_replayed_in_the_same_round():
    order = PlaylistOrder(5, rng=random.Random(2))
    order.set_shuffle(True)
    first = order.advance(False)
    target = order.upcoming()[-1]
    order.jump_to(target)
    rest = _drain(order)
    assert target not in rest
    assert sorted([first, target] + rest) == list(range(5))


def test_appended_tracks_join_the_current_shuffle_round():
    order = PlaylistOrder(3, rng=random.Random(4))
    order.set_shuffle(True)
    played = [order.advance(False)]
    order.append(2)
    played += _drain(order)
    assert sorted(played) == [0, 1, 2, 3, 4]


def test_remove_remaps_indices_and_drops_removed_tracks():
    order = PlaylistOrder(6, rng=random.Random(5))
    order.set_shuffle(True)
    order.advance(False)
    current = order.current
    removed = [i for i in range(6) if i != current][:2]
    order.remove(removed)
    assert order.count == 4
    remaining = _drain(order)
    assert len(remaining) == 3
    assert all(0 <= i < 4 for i in remaining + [order.current])
    assert len(set(remaining)) == 3


def test_removing_the_current_track_resets_current():
    order = PlaylistOrder(3)
    order.jump_to(1)
    order.remove([1])
    assert order.current == -1
    assert order.count == 2


def test_sequential_remove_before_current_shifts_it():
    order = PlaylistOrder(4)
    order.jump_to(3)
    order.remove([0, 1])
    assert order.current == 1
    assert order.advance(False) is None


def test_move_keeps_pointing_at_the_same_tracks():
    order = PlaylistOrder(4, rng=random.Random(3))
    order.set_shuffle(True)
    order.advance(False)
    labels = ["a", "b", "c", "d"]
    upcoming_labels = [labels[i] for i in order.upcoming()]
    labels.insert(0, labels.pop(3))
    order.move(3, 0)
    assert [labels[i] for i in order.upcoming()] == upcoming_labels


# ---------------------------------------------------------- deteccion de fallo
def test_playback_failed_classification():
    # Evento de error (archivo inexistente en libVLC 3: Ended + evento).
    assert playback_failed(True, False, True, 0, 0)
    assert playback_failed(False, True, False, 0, 0)
    # Archivo corrupto: Ended sin largo ni avance.
    assert playback_failed(False, False, True, 0, 0)
    # Final normal, y stream que si sono (largo 0 pero el tiempo avanzo).
    assert not playback_failed(False, False, True, 2000, 1800)
    assert not playback_failed(False, False, True, 0, 5000)
    # Mientras sigue reproduciendo nunca es fallo.
    assert not playback_failed(True, False, False, 0, 0)
