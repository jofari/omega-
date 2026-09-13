# OMEGA — Brief de conception

Assistant vocal personnel, style Jarvis/Iron Man, teinte violette. Interface web locale, boucle
voix <-> Hermes via Telegram.

**Principe n°0 : OMEGA est un OUTIL DE TRAVAIL réel, pas un gadget.** La voix est un INPUT parmi
d'autres ; la valeur est dans (1) l'EXÉCUTION réelle de tâches — Hermes fait vraiment le travail
(fichiers, recherches, code via Claude, projet ARIT/BETA), pas un simple écho de chat — et (2) un
COCKPIT qui affiche les VRAIES données de l'écosystème (usage Claude Code, tokens OpenRouter,
état des projets), pas des placeholders. Objectif n°1 : la fluidité de l'échange. Objectif n°0 :
que ce soit un instrument sérieux qu'on utilise tous les jours.

## Périmètre MVP (demain)

1. **App web locale** — HTML/CSS/JS violet « Omega », lancée en local (navigateur).
2. **Boucle voix complète** : l'utilisateur parle -> transcription (Whisper local) -> envoi à
   Hermes (Telegram) -> la réponse d'Hermes est lue à voix haute (voix Microsoft / edge-tts).
   La tâche dictée est une VRAIE demande de travail (pas un test), et la réponse est un vrai
   résultat.
3. **Cockpit de base** : état de la conversation, dernier échange, indicateur « en réflexion »,
   et les PREMIÈRES vraies métriques (cf. § Métriques).

## Métriques (vraies, pas factices — autant que l'accès le permet au MVP)

- Usage Claude Code (via `claude /usage` / `claude auth status` si accessible localement).
- Tokens OpenRouter (via l'API OpenRouter si la clé est fournie, sinon affiché comme
  « à configurer », jamais un faux chiffre).
- État de la file : tâches en cours / dernière réponse.

## Hors périmètre MVP (phase 2)

LM local de réflexion · MCP pour skills/mémoire · liaison Obsidian · métriques Claude Code /
OpenRouter détaillées · portage desktop.

## Architecture

```
[ micro / navigateur ]  <->  backend Oméga (FastAPI, local)  <->  Telegram  <->  Hermes
     (violet UI)              - /stt  (Whisper)
                              - /tts  (edge-tts)
                              - /chat (envoyer/lire via Telegram)
                              - serve le frontend statique
```

## Stack technique

- **Backend** : Python 3.12, FastAPI + uvicorn. Pas de framework JS.
- **STT** : `faster-whisper` (CTranslate2), modèle `small` (compromis latence/qualité) — offline.
- **TTS** : `edge-tts` (voix neuronales Microsoft gratuites). Voix FR naturelle (ex. `fr-FR-DeniseNeural`).
- **Telegram** : `Telethon` (client user = compte Jonas), envoie au bot Hermes et lit ses réponses.
- **Frontend** : HTML/CSS/JS vanilla, thème sombre violet (accent ~ `#7c3aed`), canvas/animations légères.

## Fluidité (priorité n°1 — à respecter dans le code)

1. **Jamais bloquer l'UI** : tout le pipeline voix (STT -> envoi Telegram -> attente -> TTS) est
   asynchrone. L'enregistrement, l'envoi et la lecture sont des étapes non-bloquantes.
2. **Indicateur d'état visible** : « j'écoute » -> « je transcris » -> « en réflexion (Hermes) »
   -> « je réponds ». L'utilisateur sait toujours où on en est pendant la latence Telegram.
3. **Latence STT minimale** : modèle whisper `small` (pas `large`), VAD pour couper le silence,
   début de traitement dès la fin de phrase si possible.
4. **TTS dès réception** : générer/lancer l'audio dès que la réponse Telegram arrive (pas de
   buffer inutile). Lecture fluide, éventuellement streaming.
5. **Micro sensible mais simple** : un bouton « parler » (push-to-talk) + option «vad auto».
   MVP = un seul bouton, robuste.

## Connexion Telegram (le seul point de config externe)

Telethon requiert `api_id`, `api_hash` et une session du compte Jonas (login une fois via
`app.login()` / téléphone + code). Tout ça dans un `.env` local, jamais commité. Le bot Hermes
= l'ID de chat existant (utilisateur 8869675077). Documenter le premier lancement en clair.

## Contraintes

- **Cross-platform** : dev/test sur Linux (VPS), déploiement final Windows. Chemins en
  `pathlib`, aucun séparateur codé en dur, encodage UTF-8 partout (console Windows cp1252).
- **Pas de dépendance fermée** : Whisper local + edge-tts gratuite + Telethon = tout est
  installable via `pip`.
- **Pas de clé en dur** : tous les secrets (Telegram api_id/hash) passent par `.env`.
- **Le backend doit tourner en `uvicorn`** avec un `requirements.txt` figé et un `README` de
  lancement pas-à-pas pour Windows.

## Livrable attendu

Un dossier `Omega/` :
```
Omega/
  app.py            (FastAPI : routes /stt /tts /chat + fichiers statiques)
  static/index.html (UI violette Omega)
  static/style.css
  static/app.js     (bouton parler, enregistrement micro, appels /stt /tts /chat, état)
  telegram_client.py (Telethon : login, envoyer, lire les réponses du bot)
  stt.py            (faster-whisper, transcrire un fichier audio)
  tts.py            (edge-tts, synthétiser + jouer)
  config.py         (chemins, .env)
  requirements.txt
  README.md         (install + lancement Windows pas-à-pas)
  .env.example      (TELEGRAM_API_ID=... etc.)
```

## Spécifications d'implémentation (à suivre à la lettre)

Routes FastAPI :
- `POST /stt` : reçoit un fichier audio (`UploadFile`), rend `{"text": "..."}` via faster-whisper.
- `POST /tts` : reçoit `{"text": "..."}`, rend un flux audio (ou un fichier) via edge-tts.
- `POST /chat` : reçoit `{"text": "..."}`, envoie au bot Hermes via Telegram, attend la réponse,
  rend `{"reply": "..."}`.
- `GET /` : sert `static/index.html` (StaticFiles monté sur `/static`).

Dégradation Telegram : si `api_id`/`api_hash` absents du `.env`, `/chat` rend un JSON clair
(`{"error": "Telegram non configuré — complète .env"}`), et l'app démarre quand même sans
planter. Jamais de crash au démarrage sur une config incomplète.

Install (venv déjà créé à `Omega/.venv`) :
- `uv pip install --python /root/Omega/.venv/bin/python fastapi "uvicorn[standard]" faster-whisper edge-tts telethon python-dotenv python-multipart`

Vérification avant de finir : `python -c "import app"` sans erreur, et `uvicorn` démarre.
Claude Code rend : la liste des fichiers créés, toute erreur non résolue, et la commande de
lancement exacte.