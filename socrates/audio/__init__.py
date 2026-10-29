"""Entrada e saída de som: microfone e alto-falante."""

TAXA_MIC = 16_000    # Whisper trabalha em 16 kHz
TAXA_VOZ = 24_000    # edge-tts entrega áudio em 24 kHz


class ErroAudio(Exception):
    """Microfone ou alto-falante indisponível."""


def importar_sounddevice():
    """Importa só quando precisa, para o modo texto funcionar sem placa de som."""
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        raise ErroAudio(
            "Não consegui acessar o som do computador. "
            "Rode: .venv\\Scripts\\python -m pip install -r requirements.txt"
        ) from e
    return sd
