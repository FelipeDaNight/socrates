"""Estado global das ferramentas zerado antes de cada teste."""

import pytest


@pytest.fixture(autouse=True)
def _sem_pastas_do_usuario(tmp_path, monkeypatch):
    """Os testes nunca leem nem gravam em Documentos\\Socrates de verdade."""
    from socrates.estudo import trilha
    monkeypatch.setattr(trilha, "PASTA_AUTO", tmp_path / "trilhas-auto")
    yield


@pytest.fixture(autouse=True)
def _estado_limpo():
    from socrates import ferramentas
    ferramentas.SOM_LIGADO.clear()
    ferramentas.PENDENTE = None
    ferramentas.LEMBRANCA = None
    yield
    ferramentas.SOM_LIGADO.clear()
