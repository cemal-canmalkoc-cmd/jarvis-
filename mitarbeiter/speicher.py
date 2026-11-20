"""Verschlüsselte Kundendatenbank (DSGVO): data/crm.enc, Schlüssel nur als GitHub-Secret CRM_KEY."""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet

LEER = {"kandidaten": {}, "arbeitgeber": {}, "vorgestellt": [], "verarbeitet": [], "letzter_bericht": "", "protokoll": []}


def neuer_schluessel() -> str:
    return Fernet.generate_key().decode()


class Speicher:
    def __init__(self, pfad: Path, schluessel: str | None) -> None:
        self.pfad = pfad
        self.fernet = Fernet(schluessel.encode()) if schluessel else None

    def laden(self) -> dict:
        if not self.pfad.exists():
            return json.loads(json.dumps(LEER))
        roh = self.pfad.read_bytes()
        if self.fernet:
            roh = self.fernet.decrypt(roh)
        daten = json.loads(roh)
        for k, v in LEER.items():
            daten.setdefault(k, json.loads(json.dumps(v)))
        return daten

    def speichern(self, daten: dict) -> None:
        daten["verarbeitet"] = daten["verarbeitet"][-2000:]
        daten["protokoll"] = daten["protokoll"][-500:]
        roh = json.dumps(daten, ensure_ascii=False, indent=1).encode()
        if self.fernet:
            roh = self.fernet.encrypt(roh)
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        self.pfad.write_bytes(roh)
