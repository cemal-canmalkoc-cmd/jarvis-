@echo off
chcp 65001 >nul
title Meme-Coin-Bot (ECHTES GELD)
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python fehlt. Bitte von https://www.python.org/downloads/ installieren
  echo und bei der Installation "Add Python to PATH" anhaken. Danach START.bat erneut oeffnen.
  pause
  exit /b
)

echo Installiere benoetigte Pakete ...
python -m pip install --quiet --disable-pip-version-check requests base58 cryptography
if errorlevel 1 (
  echo Installation fehlgeschlagen. Internetverbindung pruefen.
  pause
  exit /b
)

echo.
echo ================================================================
echo  NUR den Private Key einer EIGENEN BOT-WALLET mit wenig SOL!
echo  Niemals die Haupt-Wallet. Der Key bleibt auf diesem PC.
echo ================================================================
set /p BOT_PRIVATE_KEY=Private Key der Bot-Wallet einfuegen (Rechtsklick) und Enter: 
if "%BOT_PRIVATE_KEY%"=="" (
  echo Kein Key eingegeben.
  pause
  exit /b
)
cls
python memebot.py --profil aggressiv --live
set BOT_PRIVATE_KEY=
pause
