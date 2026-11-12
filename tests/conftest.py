"""Estado global das ferramentas zerado antes de cada teste."""

import pytest


@pytest.fixture(autouse=True)
def _estado_limpo():
    from socrates import ferramentas
    ferramentas.SOM_LIGADO.clear()
    ferramentas.PENDENTE = None
    ferramentas.LEMBRANCA = None
    yield
    ferramentas.SOM_LIGADO.clear()
