"""Einmalig ausführen: python -m mitarbeiter.schluessel  -> Ausgabe als GitHub-Secret CRM_KEY speichern."""
from .speicher import neuer_schluessel

if __name__ == "__main__":
    print(neuer_schluessel())
