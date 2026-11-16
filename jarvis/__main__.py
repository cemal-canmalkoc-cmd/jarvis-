"""Jarvis Kommandozeile.

  python -m jarvis run              Ordner + E-Mail verarbeiten, Shortlist erstellen
  python -m jarvis run --web        zusätzlich öffentliche Stellengesuche im Web suchen
  python -m jarvis run --web --focus "Pflegefachfrau Psychiatrie Bern"
  python -m jarvis list             alle Kandidaten anzeigen
  python -m jarvis status <ID> kontaktiert|interessiert|kein_interesse|vermittelt
  python -m jarvis serve            Server starten (Formular, WhatsApp, Telefon, Autopilot)
  python -m jarvis befehl "ruf die Top 3 an"   Jarvis-Befehl lokal testen
  python -m jarvis morgen           Morgenlauf sofort ausführen
"""
from __future__ import annotations

import argparse
import logging

from . import pipeline, store


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(prog="jarvis", description="Automatisierte Personalfindung Schweiz")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Kandidaten sammeln, prüfen und Shortlist erstellen")
    r.add_argument("--web", action="store_true", help="öffentliche Stellengesuche im Web suchen")
    r.add_argument("--focus", action="append", help="eigener Suchfokus fürs Web (mehrfach möglich)")
    r.add_argument("--no-email", action="store_true")
    r.add_argument("--no-folder", action="store_true")

    sub.add_parser("list", help="alle Kandidaten anzeigen")
    s = sub.add_parser("status", help="Kontaktstatus setzen")
    s.add_argument("key")
    s.add_argument("status", choices=store.STATUSES)

    sv = sub.add_parser("serve", help="Server starten")
    sv.add_argument("--port", type=int, default=int(__import__("os").environ.get("PORT", "8000")))
    b = sub.add_parser("befehl", help="Befehl an Jarvis (wie per WhatsApp)")
    b.add_argument("text", nargs="+")
    sub.add_parser("morgen", help="Morgenlauf sofort ausführen")

    args = p.parse_args()
    if args.cmd == "run":
        stats = pipeline.run(use_folder=not args.no_folder, use_email=not args.no_email,
                             use_web=args.web, web_focuses=args.focus)
        print("\n=== Jarvis Tagesbericht ===")
        for k, v in stats.items():
            print(f"{k:>12}: {v}")
    elif args.cmd == "list":
        conn = store.connect()
        for row in store.list_all(conn):
            print(" | ".join(str(x) for x in row))
    elif args.cmd == "status":
        store.set_status(store.connect(), args.key, args.status)
        print("Status gespeichert.")
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("jarvis.server:app", host="0.0.0.0", port=args.port, proxy_headers=True)
    elif args.cmd == "befehl":
        from . import agent
        print(agent.handle_owner(" ".join(args.text)))
    elif args.cmd == "morgen":
        from . import autopilot
        print(autopilot.morning(force=True))


if __name__ == "__main__":
    main()
