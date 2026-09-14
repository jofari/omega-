@echo off
setlocal
title Omega - Assistant vocal

rem ------------------------------------------------------------------
rem  Lanceur Windows pour Omega.
rem  Double-cliquer sur ce fichier (ou l'executer depuis un terminal).
rem  Relancable a volonte : ne cree ni ne modifie aucun fichier.
rem ------------------------------------------------------------------

rem Se placer dans le dossier du script, quel que soit le lecteur.
cd /d "%~dp0"

rem Forcer l'UTF-8 dans Python (accents dans la console et les logs).
set PYTHONUTF8=1

rem Verifier la presence du fichier de configuration.
if not exist ".env" (
    echo.
    echo [ATTENTION] Le fichier .env est introuvable dans %CD%
    echo             Copier .env.example en .env puis le completer
    echo             ^(TELEGRAM_API_ID, TELEGRAM_API_HASH, HERMES_TARGET^).
    echo             Voir README.md, section "Installation (Windows)".
    echo.
    pause
    exit /b 1
)

rem Activer l'environnement virtuel s'il existe.
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo [OK] Environnement virtuel .venv active.
) else (
    echo [INFO] Pas de .venv trouve : utilisation du Python systeme.
)

rem Verifier que Python est accessible.
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERREUR] Python est introuvable dans le PATH.
    echo          Installer Python 3.12 ou creer le .venv ^(voir README.md^).
    echo.
    pause
    exit /b 1
)

rem Ouvrir le navigateur par defaut (apres un court delai, le temps que le
rem serveur demarre). Lance en arriere-plan pour ne pas bloquer le script.
echo [INFO] Ouverture du navigateur sur http://127.0.0.1:8000 ...
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"

rem Lancer le serveur (Ctrl+C pour l'arreter).
echo [INFO] Demarrage d'Omega sur http://127.0.0.1:8000 ^(Ctrl+C pour arreter^)...
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000

echo.
echo [INFO] Omega s'est arrete ^(code %ERRORLEVEL%^).
pause
endlocal
