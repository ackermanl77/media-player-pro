"""Aislamiento comun a toda la suite.

MainWindow lee y escribe ~/.reproductor_multimedia_pro/{settings,session}.json
al construirse y al cerrarse (ver player/settings.py), y player/logs.py usa
%LOCALAPPDATA%. Ninguna prueba debe tocar el estado real del usuario: aqui se
redirigen ambos, para todas las pruebas, a una carpeta temporal propia de
cada prueba. (Las pruebas que ya parchean Path.home por su cuenta siguen
funcionando: pathlib.Path es la misma clase en todos los modulos.)"""
import pathlib

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_state(monkeypatch, tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata")))
    return home
