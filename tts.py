"""Synthese vocale via edge-tts (voix neuronales Microsoft, gratuites)."""

from collections.abc import AsyncIterator
from pathlib import Path

import edge_tts

from config import TTS_VOICE


async def stream(text: str) -> AsyncIterator[bytes]:
    """Genere l'audio (mp3) en streaming : chaque chunk est cede des qu'il arrive du service.

    Rien n'est ecrit sur disque ; le serveur relaie les chunks au navigateur qui commence
    la lecture sans attendre la fin de la synthese.
    """
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio" and chunk["data"]:
            yield chunk["data"]


async def synthesize(text: str, output_path: Path) -> Path:
    """Genere un fichier audio (mp3) complet et renvoie son chemin (usage script/test)."""
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    await communicate.save(str(output_path))
    return output_path
