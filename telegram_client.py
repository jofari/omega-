"""Client Telegram (Telethon, compte utilisateur Jonas) : envoie a Hermes et lit sa reponse.

Premier lancement : lance `python telegram_client.py` pour te connecter une fois
(telephone + code de confirmation). La session est ensuite sauvegardee sur disque
(fichier `omega_session.session`) et reutilisee automatiquement.

La cible (HERMES_TARGET dans .env) doit etre le @username du BOT Hermes — pas ton propre
ID utilisateur, sinon les messages partent dans "Messages enregistres" et rien ne repond.
"""

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient, errors, events

from config import (
    HERMES_TARGET,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_REPLY_TIMEOUT,
    TELEGRAM_SESSION_PATH,
    force_utf8_console,
    hermes_target_is_configured,
    telegram_is_configured,
)

force_utf8_console()

logger = logging.getLogger("omega.telegram")

_client: Optional[TelegramClient] = None
_target_entity = None  # entite Telethon resolue une fois (evite un ResolveUsername par message)
_lock = asyncio.Lock()


def is_configured() -> bool:
    return telegram_is_configured()


async def _get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient(str(TELEGRAM_SESSION_PATH), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    if not _client.is_connected():
        # connect() lance aussi la boucle de reception des updates : les handlers
        # d'evenements (send_and_wait) fonctionnent sans run_until_disconnected().
        await _client.connect()
    if not await _client.is_user_authorized():
        raise RuntimeError(
            "Session Telegram non authentifiee. Lance d'abord : "
            "python telegram_client.py (telephone + code)."
        )
    return _client


async def _get_target(client: TelegramClient):
    """Resout HERMES_TARGET (@username ou ID numerique) en entite Telethon, avec cache."""
    global _target_entity
    if _target_entity is not None:
        return _target_entity
    if not hermes_target_is_configured():
        raise RuntimeError("HERMES_TARGET non configuré — mets le @username du bot Hermes dans .env")

    try:
        entity = await client.get_entity(HERMES_TARGET)
    except (ValueError, TypeError, errors.RPCError) as exc:
        entity = None
        if isinstance(HERMES_TARGET, int):
            # Un ID numerique n'est resolvable que si la session connait deja l'entite :
            # charger les dialogues remplit ce cache, puis on reessaie.
            try:
                await client.get_dialogs()
                entity = await client.get_entity(HERMES_TARGET)
            except (ValueError, TypeError, errors.RPCError):
                entity = None
        if entity is None:
            raise RuntimeError(
                f"Cible Telegram introuvable ({HERMES_TARGET!r}) : vérifie HERMES_TARGET dans .env "
                f"(@username du bot Hermes). Détail : {exc}"
            ) from exc

    me = await client.get_me()
    if me is not None and getattr(entity, "id", None) == me.id:
        raise RuntimeError(
            f"HERMES_TARGET ({HERMES_TARGET!r}) est TON propre compte : les messages iraient dans "
            "« Messages enregistrés ». Mets le @username du bot Hermes."
        )

    _target_entity = entity
    return entity


async def send_and_wait(text: str, timeout: float = TELEGRAM_REPLY_TIMEOUT) -> str:
    """Envoie `text` a Hermes et renvoie sa premiere reponse texte.

    Listener evenementiel (events.NewMessage) : la reponse est resolue a l'instant ou
    elle arrive, sans polling ni appel API repete.
    """
    if not is_configured():
        raise RuntimeError("Telegram non configuré — complète .env")

    async with _lock:
        client = await _get_client()
        target = await _get_target(client)

        loop = asyncio.get_running_loop()
        reply: asyncio.Future[str] = loop.create_future()

        async def _on_reply(event: events.NewMessage.Event) -> None:
            if not reply.done() and event.message.message:
                reply.set_result(event.message.message)

        builder = events.NewMessage(chats=target, incoming=True)
        client.add_event_handler(_on_reply, builder)  # enregistre AVANT l'envoi : aucune fenetre ratee
        try:
            await client.send_message(target, text)
            return await asyncio.wait_for(reply, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Pas de réponse d'Hermes en {timeout:g} s.") from None
        finally:
            client.remove_event_handler(_on_reply, builder)


async def close() -> None:
    """Deconnecte proprement le client (a l'arret du serveur)."""
    if _client is not None and _client.is_connected():
        await _client.disconnect()


async def interactive_login() -> None:
    """A lancer une seule fois manuellement pour creer la session Telethon."""
    client = TelegramClient(str(TELEGRAM_SESSION_PATH), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()
    print(f"Connecté. Session sauvegardée : {TELEGRAM_SESSION_PATH}.session")
    if hermes_target_is_configured():
        try:
            entity = await _get_target(client)
            name = getattr(entity, "username", None) or getattr(entity, "title", None) or entity.id
            print(f"Cible Hermes OK : {name} (id {entity.id})")
        except RuntimeError as exc:
            print(f"Attention : {exc}")
    else:
        print("HERMES_TARGET absent du .env : ajoute le @username du bot Hermes avant d'utiliser /chat.")
    await client.disconnect()


if __name__ == "__main__":
    if not is_configured():
        print("Configure TELEGRAM_API_ID et TELEGRAM_API_HASH dans .env avant de lancer ce script.")
    else:
        asyncio.run(interactive_login())
