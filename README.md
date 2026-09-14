# Omega — Assistant vocal personnel (MVP)

Assistant vocal local (theme violet, style Jarvis) qui relie une boucle voix
(Whisper local -> Telegram -> Hermes -> edge-tts) et un cockpit affichant l'etat
reel de la conversation et des metriques disponibles.

## Prerequis

- Python 3.12 (Windows ou Linux)
- Un microphone (pour la partie vocale, dans un navigateur qui autorise `getUserMedia`,
  donc de preference `http://localhost`)
- Un compte Telegram (le tien, "Jonas") avec `api_id` / `api_hash` obtenus une fois sur
  https://my.telegram.org (section "API development tools")
- Le `@username` du BOT Hermes (celui a qui tu ecris dans Telegram). Attention : ce n'est
  PAS ton propre ID utilisateur — un message envoye a ton ID finit dans "Messages
  enregistres" et Hermes ne repond jamais.

## Installation (Windows, pas a pas)

1. Ouvrir un terminal (PowerShell) dans le dossier `Omega/`.
2. Creer et activer l'environnement virtuel (si pas deja fait) :
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
3. Installer les dependances figees :
   ```powershell
   pip install -r requirements.txt
   ```
4. Copier le fichier d'exemple d'environnement puis le completer :
   ```powershell
   copy .env.example .env
   notepad .env
   ```
   Renseigner au minimum `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` et `HERMES_TARGET`
   (le `@username` du bot Hermes, ex. `HERMES_TARGET=@hermes_bot` ; un ID numerique
   est accepte aussi, mais jamais ton propre ID).

5. Premiere connexion Telegram (une seule fois, cree le fichier de session) :
   ```powershell
   python telegram_client.py
   ```
   Suivre les instructions dans le terminal (numero de telephone, puis code recu
   par Telegram). Une fois connecte, un fichier `omega_session.session` apparait
   dans le dossier — ne pas le commiter, il vaut une session active (il est
   couvert par le `.gitignore`). Le script verifie ensuite `HERMES_TARGET` et
   affiche la cible resolue (ou une alerte si elle pointe vers ton propre compte).

6. Lancer le serveur :
   ```powershell
   uvicorn app:app --host 127.0.0.1 --port 8000
   ```
   Le modele Whisper est pre-charge en arriere-plan au demarrage (premier lancement :
   telechargement du modele `small`, ~500 Mo) ; le cockpit affiche "chargement" puis "pret".

7. Ouvrir `http://127.0.0.1:8000/` dans le navigateur.

Si des accents s'affichent mal ou provoquent une erreur dans la console (encodage
cp1252), l'app force deja l'UTF-8 ; en complement tu peux lancer `set PYTHONUTF8=1`
(PowerShell : `$env:PYTHONUTF8=1`) avant `uvicorn`.

## Lancement Windows (start.bat)

Une fois l'installation terminee (etapes 1 a 5 ci-dessus), il suffit de
double-cliquer sur `START.BAT` a la racine du projet. Le script :

1. se place dans son propre dossier (fonctionne depuis n'importe quel lecteur) ;
2. force `PYTHONUTF8=1` pour eviter les problemes d'accents dans la console ;
3. verifie que `.env` existe, sinon affiche un avertissement et s'arrete ;
4. active `.venv\Scripts\activate.bat` s'il existe (sinon utilise le Python du PATH) ;
5. ouvre le navigateur par defaut sur `http://127.0.0.1:8000` (apres 3 s, le
   temps que le serveur demarre) ;
6. lance `python -m uvicorn app:app --host 127.0.0.1 --port 8000`.

`Ctrl+C` dans la fenetre arrete le serveur ; la fenetre reste ouverte pour lire
les eventuels messages d'erreur. Le script est relancable a volonte : il ne cree
ni ne modifie aucun fichier. Equivalent manuel depuis un terminal :

```bat
START.BAT
```

## Installation (Linux / dev)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python telegram_client.py   # premiere connexion Telegram
uvicorn app:app --host 127.0.0.1 --port 8000
```

## Utilisation

1. Maintenir le bouton violet "Parler" enfonce, parler, relacher (relacher hors du
   bouton, ou changer de fenetre, arrete aussi l'enregistrement).
2. Le pipeline enchaine automatiquement : transcription locale (Whisper) ->
   envoi a Hermes via Telegram -> attente de la reponse (jusqu'a
   `TELEGRAM_REPLY_TIMEOUT`, 180 s par defaut) -> lecture a voix haute (edge-tts,
   en streaming : la voix demarre des les premiers octets recus). L'indicateur
   d'etat en haut a droite montre l'etape en cours (j'ecoute / je transcris / en
   reflexion / je reponds). Appuyer sur "Parler" pendant la lecture la coupe.
3. Le panneau "Cockpit" affiche le dernier echange, l'etat de la file, l'etat du
   modele Whisper et les metriques disponibles (Claude Code, OpenRouter).

## Degradation sans configuration

- Si `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` sont absents du `.env`, l'app
  demarre normalement mais `/chat` renvoie
  `{"error": "Telegram non configuré — complète .env"}` au lieu de planter.
- Si `HERMES_TARGET` est absent, `/chat` renvoie une erreur JSON explicite et le
  cockpit affiche "HERMES_TARGET manquant".
- Si `OPENROUTER_API_KEY` est absent, le cockpit affiche "à configurer" pour
  cette metrique (jamais un chiffre invente).
- La metrique "Claude Code" tente `claude auth status` en local ; si la CLI
  `claude` n'est pas installee ou accessible, le cockpit l'indique clairement.
- Les metriques de `/status` sont calculees hors de l'event loop et mises en cache
  (`STATUS_CACHE_TTL`, 30 s) ; une metrique en echec est affichee en erreur sans
  faire tomber les autres.

## Securite (acces local uniquement)

Hermes execute de vraies actions via ton compte Telegram, donc `/chat`, `/stt` et
`/tts` refusent (403) toute requete qui ne vient pas de la page Omega elle-meme :

- le header `Host` doit etre local (`127.0.0.1`, `localhost`, `::1`), ce qui bloque le
  DNS rebinding ; pour un acces depuis une autre machine du LAN, ajoute son adresse
  dans `OMEGA_ALLOWED_HOSTS` ;
- l'`Origin` (ou le `Referer`) du navigateur doit etre local : une page web tierce
  ouverte dans le meme navigateur est rejetee ;
- un token partage, injecte dans la page par le backend et renvoye par `app.js` dans
  le header `X-Omega-Token`, est obligatoire. Par defaut il change a chaque
  demarrage (recharge la page apres un redemarrage) ; fixe `OMEGA_SECRET` dans
  `.env` pour un token stable (utile avec `--reload` ou pour des appels `curl`).

Le `.env` et les fichiers `*.session` sont exclus de git par le `.gitignore`.

## Structure

```
Omega/
  app.py              FastAPI : routes /stt /tts /chat /status + fichiers statiques,
                      garde anti-CSRF, warm-up Whisper, cache des metriques
  static/index.html   UI violette Omega
  static/style.css
  static/app.js       bouton parler (pointer events), micro, appels /stt /tts /chat,
                      lecture TTS en streaming, etats
  telegram_client.py  Telethon : login, envoyer, attendre la reponse du bot (evenementiel)
  stt.py              faster-whisper, transcrire un fichier audio (thread)
  tts.py              edge-tts, synthetiser une reponse (streaming)
  config.py           chemins, chargement .env (jamais de crash sur config incomplete)
  requirements.txt    dependances figees (pip freeze)
  .env.example        variables a renseigner
  .gitignore          .env, *.session, tmp/, __pycache__/, .venv/
```

## Lancement exact (rappel)

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```
