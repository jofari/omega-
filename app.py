"""Omega — backend FastAPI local : STT, TTS, pont Telegram vers Hermes, cockpit.

Regle n°1 (fluidite) : rien de bloquant dans l'event loop. Le CPU (Whisper), les
subprocess et les appels HTTP synchrones tournent dans des threads ; le TTS est streame.
"""

import asyncio
import json
import logging
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import (
    OMEGA_TOKEN,
    OPENROUTER_API_KEY,
    STATIC_DIR,
    STATUS_CACHE_TTL,
    TMP_DIR,
    TRUSTED_HOSTS,
    force_utf8_console,
    hermes_target_is_configured,
    telegram_is_configured,
)
import stt
import telegram_client
import tts

force_utf8_console()  # console Windows cp1252 : accents dans les logs/exceptions sans crash

logger = logging.getLogger("omega")
if not logging.getLogger().handlers:  # uvicorn ne configure pas le logger racine
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s:     %(name)s — %(message)s")
logger.setLevel(logging.INFO)  # nos logs (warm-up Whisper, echecs) en INFO, sans le bruit des libs


class ChatRequest(BaseModel):
    text: str


class TTSRequest(BaseModel):
    text: str


# --- Etat cockpit (en memoire, best-effort) ---
_state = {
    "pending_chat_requests": 0,
    "last_exchange": None,  # {"user": str, "hermes": str, "at": float}
}


def _clean_tmp_dir() -> None:
    """Supprime les fichiers temporaires orphelins (anciens mp3 TTS, uploads STT interrompus)."""
    for path in TMP_DIR.iterdir():
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _clean_tmp_dir()
    # Warm-up Whisper dans un thread daemon : le serveur repond tout de suite, la 1re requete
    # /stt ne paie pas le chargement du modele, et un arret n'attend pas la fin du chargement.
    threading.Thread(target=stt.warm_up, name="whisper-warmup", daemon=True).start()
    yield
    await telegram_client.close()


app = FastAPI(title="Omega", lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_as_json(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Toutes les erreurs HTTP en {"error": "..."} : app.js n'a qu'un seul format a gerer.
    return JSONResponse(
        {"error": str(exc.detail)}, status_code=exc.status_code, headers=getattr(exc, "headers", None)
    )


# --- Securite locale -------------------------------------------------------------------
# Hermes execute de VRAIES actions via le compte Telegram : n'importe quelle page web ouverte
# dans le meme navigateur pourrait sinon faire fetch("http://127.0.0.1:8000/chat", ...).


def _is_trusted(value: str | None) -> bool:
    """Vrai si un header Host, ou une URL (Origin/Referer), pointe vers un hote de confiance."""
    if not value:
        return False
    try:
        hostname = urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return False
    return hostname in TRUSTED_HOSTS


async def require_local_host(request: Request) -> None:
    """Le header Host doit etre local : bloque le DNS rebinding (attacker.com -> 127.0.0.1)."""
    if not _is_trusted(request.headers.get("host")):
        raise HTTPException(
            status_code=403,
            detail="Hôte non autorisé : accès local uniquement (ou OMEGA_ALLOWED_HOSTS dans .env)",
        )


async def require_local_client(request: Request) -> None:
    """Garde anti-CSRF des routes qui agissent (/chat /stt /tts).

    1. Host local (voir require_local_host) ;
    2. Origin (ou Referer a defaut) local — une page tierce envoie son propre Origin, ou
       'null', et est rejetee ; les clients hors navigateur (curl) n'en envoient pas ;
    3. token partage : injecte dans index.html, renvoye par app.js dans X-Omega-Token.
    """
    await require_local_host(request)
    origin = request.headers.get("origin")
    source = origin if origin is not None else request.headers.get("referer")
    if source is not None and not _is_trusted(source):
        raise HTTPException(status_code=403, detail="Origine non autorisée")
    token = request.headers.get("x-omega-token", "")
    if not secrets.compare_digest(token.encode("utf-8", "replace"), OMEGA_TOKEN.encode("utf-8")):
        raise HTTPException(
            status_code=403, detail="Token Omega manquant ou invalide (recharge la page)"
        )


# --- STT ---------------------------------------------------------------------------------


def _transcribe_upload(data: bytes, suffix: str) -> str:
    """Ecrit l'audio sur disque puis transcrit : I/O + CPU, entierement hors event loop."""
    tmp_path = TMP_DIR / f"{uuid4().hex}{suffix}"
    try:
        tmp_path.write_bytes(data)
        return stt.transcribe(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/stt", dependencies=[Depends(require_local_client)])
async def stt_endpoint(file: UploadFile) -> JSONResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if not (suffix.startswith(".") and suffix[1:].isalnum() and len(suffix) <= 8):
        suffix = ".wav"
    data = await file.read()
    if not data:
        return JSONResponse({"text": ""})
    try:
        text = await asyncio.to_thread(_transcribe_upload, data, suffix)
    except Exception as exc:
        logger.exception("Transcription impossible")
        return JSONResponse({"error": f"Transcription impossible : {exc}", "text": ""}, status_code=500)
    return JSONResponse({"text": text})


# --- TTS ---------------------------------------------------------------------------------


@app.post("/tts", dependencies=[Depends(require_local_client)])
async def tts_endpoint(payload: TTSRequest) -> StreamingResponse:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texte vide")

    chunks = tts.stream(text)
    # On attend le 1er chunk avant de repondre : une panne edge-tts devient une vraie erreur
    # HTTP (pas un 200 tronque), et le navigateur commence a lire des sa reception.
    try:
        first = await anext(chunks)
    except StopAsyncIteration:
        raise HTTPException(status_code=502, detail="edge-tts n'a renvoyé aucun audio")
    except Exception as exc:
        logger.warning("edge-tts indisponible : %s", exc)
        raise HTTPException(status_code=502, detail=f"edge-tts indisponible : {exc}") from exc

    async def body() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in chunks:
                yield chunk
        finally:
            await chunks.aclose()

    # Rien n'est ecrit dans tmp/ : plus de mp3 orphelins.
    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


# --- Chat (pont Telegram -> Hermes) --------------------------------------------------------


@app.post("/chat", dependencies=[Depends(require_local_client)])
async def chat_endpoint(payload: ChatRequest) -> JSONResponse:
    if not telegram_is_configured():
        return JSONResponse({"error": "Telegram non configuré — complète .env"})
    if not hermes_target_is_configured():
        return JSONResponse(
            {"error": "HERMES_TARGET non configuré — mets le @username du bot Hermes dans .env"}
        )
    text = payload.text.strip()
    if not text:
        return JSONResponse({"error": "Texte vide"})

    _state["pending_chat_requests"] += 1
    try:
        reply = await telegram_client.send_and_wait(text)
    except (TimeoutError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)})
    except Exception as exc:  # erreurs Telethon/reseau : toujours un JSON propre pour le front
        logger.exception("Échange Telegram en échec")
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        _state["pending_chat_requests"] -= 1

    _state["last_exchange"] = {"user": text, "hermes": reply, "at": time.time()}
    return JSONResponse({"reply": reply})


# --- Metriques cockpit --------------------------------------------------------------------


def _claude_code_usage() -> dict:
    # shutil.which renvoie le chemin complet (claude.cmd sur Windows, que ["claude", ...]
    # ne trouverait pas).
    claude_path = shutil.which("claude")
    if claude_path is None:
        return {"status": "unavailable", "detail": "CLI `claude` introuvable localement"}
    try:
        result = subprocess.run(
            [claude_path, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
        output = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            return {"status": "error", "detail": output or f"claude auth status : code {result.returncode}"}
        return {"status": "ok", "detail": output}
    except Exception as exc:  # subprocess.TimeoutExpired, OSError, etc.
        return {"status": "unavailable", "detail": str(exc)}


def _openrouter_usage() -> dict:
    if not OPENROUTER_API_KEY:
        return {"status": "not_configured", "detail": "à configurer (OPENROUTER_API_KEY manquant)"}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "detail": "réponse OpenRouter non-JSON"}
    except Exception as exc:  # URLError, HTTPError, TimeoutError, erreurs socket...
        return {"status": "error", "detail": str(exc)}
    if isinstance(data, dict):
        return {"status": "ok", "detail": data.get("data", data)}
    return {"status": "ok", "detail": data}


class _CachedMetric:
    """Metrique calculee dans un thread, en cache `ttl` s, servie perimee pendant un rafraichissement.

    /status est polle toutes les 5 s : sans cache, `claude auth status` (subprocess) et l'appel
    OpenRouter etaient relances a chaque poll ; sans thread, ils gelaient l'event loop.
    Une metrique qui echoue renvoie {"status": "error"} et ne fait jamais tomber /status.
    """

    def __init__(self, name: str, compute: Callable[[], dict], ttl: float) -> None:
        self.name = name
        self._compute = compute
        self._ttl = ttl
        self._value: dict | None = None
        self._at = 0.0
        self._refresh: asyncio.Task | None = None

    async def get(self) -> dict:
        fresh = self._value is not None and (time.monotonic() - self._at) < self._ttl
        if not fresh and (self._refresh is None or self._refresh.done()):
            self._refresh = asyncio.create_task(self._run())
        if self._value is None:  # 1er appel : on attend le resultat
            await self._refresh
        # Sinon : valeur (eventuellement perimee) tout de suite, rafraichie en arriere-plan.
        return self._value or {"status": "error", "detail": "indisponible"}

    async def _run(self) -> None:
        try:
            value = await asyncio.to_thread(self._compute)
        except Exception as exc:
            logger.warning("Métrique %s en échec : %s", self.name, exc)
            value = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
        self._value = value
        self._at = time.monotonic()


_claude_metric = _CachedMetric("claude_code", _claude_code_usage, STATUS_CACHE_TTL)
_openrouter_metric = _CachedMetric("openrouter", _openrouter_usage, STATUS_CACHE_TTL)


@app.get("/status", dependencies=[Depends(require_local_host)])
async def status_endpoint() -> JSONResponse:
    claude, openrouter = await asyncio.gather(_claude_metric.get(), _openrouter_metric.get())
    return JSONResponse(
        {
            "queue": {
                "pending_chat_requests": _state["pending_chat_requests"],
                "last_exchange": _state["last_exchange"],
            },
            "telegram_configured": telegram_is_configured(),
            "hermes_target_configured": hermes_target_is_configured(),
            "metrics": {
                "claude_code": claude,
                "openrouter": openrouter,
                "stt": stt.status(),
            },
        }
    )


# --- Frontend -----------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", dependencies=[Depends(require_local_host)])
async def index() -> HTMLResponse:
    # Le token anti-CSRF est injecte dans la page. Une page tierce ne peut pas lire cette
    # reponse (same-origin policy), donc ne peut pas obtenir le token.
    html = await asyncio.to_thread((STATIC_DIR / "index.html").read_text, encoding="utf-8")
    return HTMLResponse(html.replace("__OMEGA_TOKEN__", OMEGA_TOKEN), headers={"Cache-Control": "no-store"})
