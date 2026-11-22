#!/bin/bash
# Mac/Linux: im Terminal  bash start.sh
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python fehlt: https://www.python.org/downloads/"; exit 1; }
python3 -m pip install --quiet requests base58 cryptography || exit 1
echo "NUR den Private Key einer EIGENEN BOT-WALLET mit wenig SOL – nie die Haupt-Wallet!"
read -rsp "Private Key der Bot-Wallet einfuegen und Enter: " BOT_PRIVATE_KEY; echo
export BOT_PRIVATE_KEY
python3 memebot.py --profil aggressiv --live
