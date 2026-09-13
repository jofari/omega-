"""Configuration centralisee d'Omega : chemins et variables d'environnement (.env).

Aucune valeur invalide ou absente ne doit faire planter l'import : tout a un defaut sur
ou vaut None, et c'est le code appelant qui degrade proprement (ex. /chat -> {"error": ...}).
"""

import logging
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("omega.config")


def force_utf8_console() -> None:
    """Force stdout/stderr en UTF-8.

    Sur Windows la console est souvent en cp1252 : un accent dans un print() ou un message
    d'exception leve UnicodeEncodeError. Idempotent, sans effet si le flux est absent
    (pythonw) ou non reconfigurable. Alternative : `set PYTHONUTF8=1`.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _env(name: str, default: str = "") -> str:
    """Valeur d'environnement nettoyee ; une variable vide vaut le defaut."""
    return os.getenv(name, "").strip() or default


def _int_or_none(raw: str) -> int | None:
    # try/except plutot qu'un test isdigit() : "²".isdigit() est vrai mais int("²") leve
    # ValueError, et rien ne doit planter a l'import.
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _float_or_default(raw: str, default: float) -> float:
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _parse_target(raw: str) -> int | str | None:
    """Cible Telegram : '@username' du bot (str) ou ID numerique (int). None si vide."""
    raw = raw.strip()
    if not raw:
        return None
    # try/except plutot que lstrip("-").isdigit() : "--5" passait le test puis int("--5")
    # levait ValueError a l'import.
    try:
        return int(raw)
    except ValueError:
        return raw


# --- Telegram (Telethon, compte utilisateur Jonas) ---
TELEGRAM_API_ID = _int_or_none(os.getenv("TELEGRAM_API_ID", ""))
TELEGRAM_API_HASH = _env("TELEGRAM_API_HASH") or None
TELEGRAM_SESSION_PATH = BASE_DIR / _env("TELEGRAM_SESSION_NAME", "omega_session")
# Destinataire des messages : le @username du BOT Hermes (ou son ID numerique).
# Volontairement SANS defaut : un ID utilisateur (le tien) enverrait les messages dans
# "Messages enregistres" au lieu du bot.
HERMES_TARGET = _parse_target(os.getenv("HERMES_TARGET", ""))
if HERMES_TARGET is None and _env("HERMES_CHAT_ID"):
    logger.warning(
        "HERMES_CHAT_ID est obsolete et ignore : renseigne HERMES_TARGET=@username_du_bot dans .env"
    )
# Les vraies taches d'Hermes prennent 30 s a 2 min : defaut genereux.
TELEGRAM_REPLY_TIMEOUT = _float_or_default(os.getenv("TELEGRAM_REPLY_TIMEOUT", ""), 180.0)

# --- STT (faster-whisper) ---
WHISPER_MODEL_SIZE = _env("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = _env("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = _env("WHISPER_COMPUTE_TYPE", "int8")

# --- TTS (edge-tts) ---
TTS_VOICE = _env("TTS_VOICE", "fr-FR-DeniseNeural")

# --- Metriques (cockpit) ---
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY") or None
# /status est polle toutes les 5 s par le front : les metriques lentes (subprocess, HTTP)
# sont recalculees au plus une fois par STATUS_CACHE_TTL secondes.
STATUS_CACHE_TTL = _float_or_default(os.getenv("STATUS_CACHE_TTL", ""), 30.0)

# --- Securite locale (anti-CSRF sur /chat /stt /tts : Hermes execute de VRAIES actions) ---
# Secret partage backend <-> page : injecte dans index.html par GET /, renvoye par app.js dans
# le header X-Omega-Token. Sans OMEGA_SECRET dans .env, un token aleatoire est genere a chaque
# demarrage (suffisant en usage local ; fixe-le pour utiliser --reload ou curl).
OMEGA_TOKEN = _env("OMEGA_SECRET") or secrets.token_urlsafe(32)
# Hotes acceptes (header Host, et Origin/Referer des requetes navigateur), sans port.
# Pour un acces depuis le LAN : OMEGA_ALLOWED_HOSTS=192.168.1.10,mon-pc.local
TRUSTED_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1"}
    | {h.strip().lower() for h in os.getenv("OMEGA_ALLOWED_HOSTS", "").split(",") if h.strip()}
)


def telegram_is_configured() -> bool:
    return TELEGRAM_API_ID is not None and TELEGRAM_API_HASH is not None


def hermes_target_is_configured() -> bool:
    return HERMES_TARGET is not None
