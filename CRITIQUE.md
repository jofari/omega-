# CRITIQUE fusionnée — à corriger (ordre de sévérité)

Corrige CHAQUE point ci-dessous. Ne casse pas ce qui marche. Puis vérifie : `python -c "import app"`
et `uvicorn` démarrent, `/status` répond sans bloquer, `/chat` sans config rend l'erreur JSON propre.

## CRITIQUE — fluidité (priorité n°1)

1. **STT bloque l'event loop** (`stt.py` + `app.py /stt`) : `stt.transcribe` est CPU-bound synchrone,
   appelé direct dans un `async def`. Il gèle tout le serveur pendant la transcription (et le 1er
   chargement du modèle). → `await asyncio.to_thread(stt.transcribe, path)`, et pré-charger le modèle
   au démarrage dans un thread (warm-up) pour pas pénaliser la 1re requête.

2. **`/status` bloque** (`app.py` `_claude_code_usage` + `_openrouter_usage`) : subprocess `claude auth
   status` (timeout 5s) et `urllib` (timeout 5s) synchrones dans le endpoint async, pollé toutes les 5s.
   → exécuter dans `to_thread`, mettre en cache (ex. 30s), et isoler chaque métrique dans son propre
   try/except (une métrique cassée ne doit pas planter tout `/status` — notamment `json.loads` non
   protégé en cas de réponse non-JSON d'OpenRouter).

3. **Telegram poll 1s** (`telegram_client.py send_and_wait`) : polling toutes les secondes = jusqu'à 1s
   de latence morte à chaque échange + appels API inutiles. → listener événementiel
   (`client.on(events.NewMessage)` + `asyncio.Future/Event`) qui résout dès l'arrivée. Garder un timeout
   généreux (les vraies tâches d'Hermes prennent 30s–2min, pas 60s → monter le défaut à ~180s).

4. **TTS bufferisé** (`app.py /tts` + `app.js`) : l'audio entier est généré puis téléchargé avant lecture
   → plusieurs secondes de silence pour les longues réponses. → streamer `edge_tts ... .stream()`
   (StreamingResponse) et lire en streaming côté front. Au minimum, lancer la lecture dès réception du
   premier chunk.

5. **`shutil.copyfileobj` bloquant** (`app.py /stt`) : I/O disque synchrone dans l'async. → `await
   file.read()` + `write_bytes`.

## CRITIQUE — bugs / robustesse

6. **`config.py` `HERMES_CHAT_ID = int(...)` plante au démarrage** si la var est vide/non-numérique
   (`ValueError` à l'import). → utiliser `_int_or_none` comme les autres, avec défaut sûr.

7. **Mauvaise cible Telegram** : `8869675077` est l'ID UTILISATEUR de Jonas, pas le bot. Envoyer un
   message à cet ID, c'est envoyer à soi-même (Saved Messages), pas à Hermes. → rends la cible
   configurable (`HERMES_TARGET` acceptant soit `@username` du bot soit un ID numérique), sans défaut
   trompeur, et documente dans README/.env.example qu'il faut mettre le @username du BOT.

8. **`app.js` : pas de `mouseleave`/`pointercancel`** sur le bouton push-to-talk → si l'utilisateur
   glisse hors du bouton avant de relâcher, l'enregistrement ne s'arrête jamais, micro ouvert, UI figée
   sur « j'ecoute ». → ajouter ces handlers qui arrêtent l'enregistrement.

9. **Windows `claude.cmd`** (`app.py _claude_code_usage`) : `subprocess.run(["claude", ...])` échoue sur
   Windows si seul `claude.cmd` existe. → utiliser le chemin renvoyé par `shutil.which("claude")`.

10. **UTF-8 console Windows (cp1252)** : les accents dans les `print()`/messages d'exception peuvent
    faire `UnicodeEncodeError`. → forcer UTF-8 (`sys.stdout.reconfigure(encoding="utf-8")`) en tête de
    `app.py` et `telegram_client.py`, et/ou documenter `set PYTHONUTF8=1`.

11. **Fuite de fichiers TTS** (`app.py /tts`) : l'audio généré n'est jamais supprimé du `tmp/` →
    croissance disque. → supprimer après envoi (`FileResponse(..., background=BackgroundTask(...))` ou
    après le streaming).

## CRITIQUE — sécurité (important : Hermes exécute de VRAIES actions)

12. **Aucun contrôle d'origine sur `/chat` `/stt` `/tts`** : n'importe quelle page web ouverte dans le
    même navigateur peut `fetch("http://127.0.0.1:8000/chat", ...)` et piloter Hermes via le vrai compte
    Telegram. → au minimum vérifier `Origin`/`Referer` contre localhost, ou exiger un secret partagé
    (`.env`) injecté par `app.js` dans un header, rejeté sinon.

13. **Pas de `.gitignore`** : `.env` (clés Telegram) et `*.session` (accès total au compte Telegram)
    risquent d'être commités. → ajouter `.gitignore` couvrant `.env`, `*.session`, `tmp/`, `__pycache__/`,
    `.venv/`.

## Vérifie avant de finir

- `python -c "import app"` OK · `uvicorn` démarre · `/status` répond vite et ne plante plus si une
  métrique échoue · `/chat` sans `.env` rend `{"error": "..."}` propre · `.gitignore` présent.
- Rapporte la liste des fichiers modifiés + toute erreur restante.