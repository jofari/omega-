"""Transcription vocale locale via faster-whisper (offline, modele 'small').

Tout ici est synchrone et CPU-bound : le serveur appelle `transcribe` via
`asyncio.to_thread` et lance `warm_up` dans un thread au demarrage pour que la
premiere requete ne paie pas le chargement du modele.
"""

import logging
import threading
from pathlib import Path

from faster_whisper import WhisperModel

from config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL_SIZE

logger = logging.getLogger("omega.stt")

_model: WhisperModel | None = None
_model_lock = threading.Lock()  # un seul chargement, meme si warm-up et 1re requete se croisent
_load_error: str | None = None


def _get_model() -> WhisperModel:
    """Charge le modele une seule fois (thread-safe). A appeler hors de l'event loop."""
    global _model, _load_error
    with _model_lock:
        if _model is None:
            logger.info(
                "Chargement du modele Whisper '%s' (%s / %s)...",
                WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
            )
            try:
                _model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
            except Exception as exc:
                _load_error = f"{type(exc).__name__}: {exc}"
                raise
            _load_error = None
            logger.info("Modele Whisper '%s' pret.", WHISPER_MODEL_SIZE)
        return _model


def warm_up() -> None:
    """Pre-charge le modele (a lancer dans un thread au demarrage). Ne leve jamais."""
    try:
        _get_model()
    except Exception:
        logger.exception("Pre-chargement Whisper impossible (la 1re requete /stt reessaiera)")


def status() -> dict:
    """Etat du modele pour le cockpit (lecture memoire, instantane)."""
    label = f"whisper {WHISPER_MODEL_SIZE} ({WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE})"
    if _model is not None:
        return {"status": "ready", "detail": f"pret — {label}"}
    if _load_error:
        return {"status": "error", "detail": _load_error}
    return {"status": "loading", "detail": f"chargement — {label}"}


def transcribe(audio_path: Path) -> str:
    """Transcrit un fichier audio en texte francais. VAD active pour couper les silences.

    Synchrone et CPU-bound : appeler via `asyncio.to_thread` depuis le serveur.
    """
    model = _get_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True, language="fr")
    return "".join(segment.text for segment in segments).strip()
