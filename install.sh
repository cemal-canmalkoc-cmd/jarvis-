#!/usr/bin/env bash
# Jarvis – Installation auf einem frischen Ubuntu-Server (z.B. Oracle Cloud "Always Free").
# Aufruf (ein Befehl, fragt alles ab):
#   curl -fsSL https://raw.githubusercontent.com/cemal-canmalkoc-cmd/jarvis-/claude/magical-pascal-95tllp/install.sh | bash
# Ohne Rückfragen (z.B. als Oracle "Initialization script"): Werte in eine Datei schreiben und
#   JARVIS_ENV_FILE=/pfad/zur/datei bash install.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

REPO="https://github.com/cemal-canmalkoc-cmd/jarvis-.git"
BRANCH="claude/magical-pascal-95tllp"
DIR="${JARVIS_DIR:-${HOME:-/root}/jarvis}"
ME="${USER:-$(id -un)}"

say() { printf "\n\033[1;32m==> %s\033[0m\n" "$*"; }
ask() {  # ask VAR "Frage" [Standard] [geheim]
  local var="$1" q="$2" def="${3:-}" secret="${4:-}" val=""
  while true; do
    if [ -n "$secret" ]; then read -rsp "$q: " val </dev/tty; echo; else
      read -rp "$q${def:+ [$def]}: " val </dev/tty; fi
    val="${val:-$def}"
    [ -n "$val" ] && break
    echo "  Bitte etwas eingeben."
  done
  printf -v "$var" '%s' "$val"
}

say "1/5 Pakete und Docker installieren (dauert 2-4 Minuten)"
sudo apt-get update -y -qq
sudo apt-get install -y -qq git curl ca-certificates iptables-persistent >/dev/null || true
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh >/dev/null
fi
sudo usermod -aG docker "$ME" || true

say "2/5 Firewall für Web (Port 80/443) öffnen"
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || \
    { sudo iptables -I INPUT 5 -p tcp -m state --state NEW --dport $p -j ACCEPT 2>/dev/null || \
      sudo iptables -I INPUT 1 -p tcp -m state --state NEW --dport $p -j ACCEPT; }
done
sudo netfilter-persistent save >/dev/null 2>&1 || true

say "3/5 Jarvis herunterladen"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q; else git clone -q -b "$BRANCH" "$REPO" "$DIR"; fi
cd "$DIR"

set_env() { # set_env KEY VALUE
  local k="$1" v="$2"
  v="${v//\\/\\\\}"; v="${v//&/\\&}"; v="${v//|/\\|}"
  if grep -q "^$k=" .env; then sed -i "s|^$k=.*|$k=$v|" .env; else echo "$k=$v" >> .env; fi
}

if [ ! -f .env ] && [ -n "${JARVIS_ENV_FILE:-}" ] && [ -f "$JARVIS_ENV_FILE" ]; then
  say "4/5 Einstellungen aus $JARVIS_ENV_FILE übernehmen"
  cp .env.example .env
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    k="${line%%=*}"; v="${line#*=}"
    set_env "$k" "$v"
  done < "$JARVIS_ENV_FILE"
  dom="$(grep '^JARVIS_DOMAIN=' .env | cut -d= -f2)"
  grep -q '^JARVIS_PUBLIC_URL=https://'"$dom"'$' .env || set_env JARVIS_PUBLIC_URL "https://$dom"
  chmod 600 .env
  rm -f "$JARVIS_ENV_FILE"
elif [ ! -f .env ]; then
  say "4/5 Einstellungen (Eingaben werden nur auf diesem Server gespeichert)"
  echo "Tipp: Werte aus deiner Notiz 'Jarvis' kopieren und hier einfügen."
  ask DOMAIN   "Deine DuckDNS-Adresse (z.B. hansa-jarvis.duckdns.org)"
  ask CLAUDE   "Claude-Schlüssel (sk-ant-..., Eingabe unsichtbar)" "" secret
  ask ADMIN    "Zugangscode für App & Siri"
  ask VERIFY   "WhatsApp-Prüfcode (Meta Verify Token)"
  ask EMAIL    "Deine E-Mail für Meldungen"
  read -rp "Meta WhatsApp-Token (leer lassen = später eintragen): " META_TOKEN </dev/tty || true
  read -rp "Meta Phone-Number-ID (leer = später): " META_ID </dev/tty || true
  read -rp "Meta App-Geheimcode (leer = später): " META_SECRET </dev/tty || true

  cp .env.example .env
  set_env ANTHROPIC_API_KEY "$CLAUDE"
  set_env JARVIS_DOMAIN "$DOMAIN"
  set_env JARVIS_PUBLIC_URL "https://$DOMAIN"
  set_env JARVIS_ADMIN_TOKEN "$ADMIN"
  set_env META_VERIFY_TOKEN "$VERIFY"
  set_env JARVIS_OWNER_EMAIL "$EMAIL"
  set_env JARVIS_WHATSAPP_NUMBER "$WANUM"
  set_env JARVIS_OWNER_WHATSAPP ""
  set_env META_WHATSAPP_TOKEN "${META_TOKEN:-}"
  set_env META_PHONE_NUMBER_ID "${META_ID:-}"
  set_env META_APP_SECRET "${META_SECRET:-}"
  chmod 600 .env
else
  say "4/5 Einstellungen vorhanden (.env) – werden beibehalten"
fi

say "5/5 Jarvis starten"
sudo docker compose up -d --build

IP=$(curl -fsS https://api.ipify.org || echo "?")
cat <<EOF

✅ Jarvis läuft!

   Formular:  https://$(grep '^JARVIS_DOMAIN=' .env | cut -d= -f2)/bewerbung
   App:       https://$(grep '^JARVIS_DOMAIN=' .env | cut -d= -f2)/app
   Server-IP: $IP   (muss bei DuckDNS eingetragen sein)

Nützliche Befehle:
   Einstellungen ändern:  nano ~/jarvis/.env   danach:  cd ~/jarvis && sudo docker compose up -d
   Protokoll ansehen:     cd ~/jarvis && sudo docker compose logs -f jarvis
   Update:                cd ~/jarvis && git pull && sudo docker compose up -d --build
EOF
