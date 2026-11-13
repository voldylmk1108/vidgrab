@echo off
title VidGrab
cd /d "%~dp0"
where python >nul 2>nul || (echo Python introuvable. Installe-le puis relance. & pause & exit /b 1)
echo Mise a jour des dependances...
python -m pip install -q -U -r requirements.txt
set SERVE_FRONT=1
set ENABLE_DOCS=1
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:8000"
echo VidGrab : http://localhost:8000 - ferme cette fenetre pour arreter le serveur.
python -m uvicorn app.main:app
pause
