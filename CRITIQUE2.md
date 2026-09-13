# CRITIQUE tour 2 — 5 défauts restants à corriger

Corrige ces 5 points. Ne casse pas le reste. Vérifie ensuite `python -c "import app"` + `uvicorn`.

1. **`requirements.txt` : `uvloop` bloque l'install Windows** (pas de wheel Windows). → écrire
   `uvloop==0.22.1; sys_platform != "win32"` (garder uvloop pour Linux, l'exclure sur Windows).

2. **`config.py` : `_int_or_none("--5")` plante** à l'import (`"--5".lstrip("-")` → `"5"`,
   `isdigit()` vrai, `int("--5")` → `ValueError`). → remplacer le corps par un try/except
   `ValueError` qui rend `raw` proprement (ou retourne None).

3. **`static/app.js` : le prompt de permission micro déclenche `window.blur`, qui coupe
   l'enregistrement avant que `getUserMedia` résolve** → premier enregistrement annulé, sans
   feedback, et ça recommence à chaque chargement. → ne stopper sur `blur` que si
   `mediaRecorder` existe déjà (guard `if (mediaRecorder) ...`), pas pendant la demande de
   permission.

4. **`static/app.js` : le poll `/status` (5s) écrase l'UI live** — pendant qu'Hermes réfléchit,
   il remplace la nouvelle transcription par l'ancien échange, et efface le texte d'erreur.
   → ne mettre à jour `last_exchange` / les champs que si l'état courant est `idle`.

5. **`app.py` : le token est injecté sans échappement** — un `OMEGA_SECRET` contenant `"` ou
   `&` tronque l'attribut meta et tout renvoie 403 sans cause visible. → `from html import
   escape` puis `html.replace("__OMEGA_TOKEN__", escape(OMEGA_TOKEN, quote=True))`.

Note `.env.example` : préciser que `--workers N` exige un `OMEGA_SECRET` fixe (sinon chaque
worker génère son propre token et tout casse).

Rapporte les fichiers modifiés + toute erreur restante.