#!/data/data/com.termux/files/usr/bin/bash
# Einrichtung des Meme-Coin-Bots auf Android (Termux)
set -e
BASIS="https://raw.githubusercontent.com/cemal-canmalkoc-cmd/jarvis-/claude/friendly-hawking-e051yv/memebot"
ZIEL="$HOME/memebot"

echo ">> Pakete installieren (dauert ein paar Minuten) ..."
yes | pkg update -y >/dev/null 2>&1 || true
pkg install -y python python-cryptography curl >/dev/null
pip install --quiet --disable-pip-version-check requests base58

echo ">> Bot herunterladen ..."
mkdir -p "$ZIEL"
for f in memebot.py live.py README.md; do
  curl -fsSL "$BASIS/$f" -o "$ZIEL/$f"
done

cat > "$PREFIX/bin/bot" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/memebot"
termux-wake-lock 2>/dev/null   # verhindert, dass Android den Bot schlafen legt
echo "NUR den Private Key einer EIGENEN BOT-WALLET mit wenig SOL - nie die Haupt-Wallet!"
read -rsp "Private Key einfuegen und Enter: " BOT_PRIVATE_KEY < /dev/tty; echo
export BOT_PRIVATE_KEY
python memebot.py --profil aggressiv --live
termux-wake-unlock 2>/dev/null
EOS
chmod +x "$PREFIX/bin/bot"

echo
echo "Fertig! Zum Starten einfach eintippen:   bot"
