"""Jarvis Kommandozeile.

  python -m jarvis run              Ordner + E-Mail verarbeiten, Shortlist erstellen
  python -m jarvis run --web        zusätzlich öffentliche Stellengesuche im Web suchen
  python -m jarvis run --web --focus "Pflegefachfrau Psychiatrie Bern"
  python -m jarvis list             alle Kandidaten anzeigen
  python -m jarvis status <ID> kontaktiert|interessiert|kein_interesse|vermittelt
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


if __name__ == "__main__":
    main()
