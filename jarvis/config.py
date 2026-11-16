"""Suchprofil und Einstellungen von Jarvis.

Hier wird festgelegt, WEN Jarvis sucht. Änderungen am Bedarf nur hier pflegen.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(os.environ.get("JARVIS_HOME", Path(__file__).resolve().parent.parent))

# .env-Datei laden (einfache KEY=VALUE-Zeilen), ohne bestehende Variablen zu überschreiben
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())
DATA_DIR = BASE_DIR / "data"
INBOX_DIR = DATA_DIR / "inbox"          # Lebensläufe (PDF/DOCX/TXT) hier ablegen
PROCESSED_DIR = DATA_DIR / "processed"  # verarbeitete Dateien landen hier
REPORT_DIR = BASE_DIR / "reports"       # tägliche Shortlists (HTML + CSV)
DB_PATH = DATA_DIR / "jarvis.sqlite3"

MODEL = os.environ.get("JARVIS_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("JARVIS_EFFORT", "medium")

# Absender-Angaben für die WhatsApp-Nachrichten
RECRUITER_NAME = os.environ.get("JARVIS_RECRUITER_NAME", "Ihr Recruiting-Team")
AGENCY_NAME = os.environ.get("JARVIS_AGENCY_NAME", "unserer Personalvermittlung")

# Wie viele Top-Kandidaten pro Tag in die Shortlist kommen
DAILY_SHORTLIST_SIZE = int(os.environ.get("JARVIS_DAILY_SIZE", "25"))

# ---------------------------------------------------------------------------
# Aktueller Bedarf Schweiz
# ---------------------------------------------------------------------------
NURSING_FIELDS = [
    "Dipl. Pflegefachperson HF/FH",
    "Akutspital",
    "Psychiatrie",
    "Geriatrie / Langzeitpflege",
    "FaGe (Fachfrau/Fachmann Gesundheit)",
]

PHYSICIAN_SPECIALTIES = [
    "Allgemeine Innere Medizin",
    "Psychiatrie",
    "Gynäkologie",
    "Radiologie",
    "Anästhesie",
    "Geriatrie",
    "Neurologie",
    "Rehabilitation",
]

REQUIREMENTS_TEXT = f"""
BEDARF SCHWEIZ (Stand aktuell)

Pflege:
- Gesuchte Bereiche: {", ".join(NURSING_FIELDS)}
- Pflicht: Berufsurkunde/Diplom + Deutsch mindestens B2.
- Ausländisches Diplom: SRK-Anerkennung erforderlich.
- Besonders interessant: SRK-Anerkennung liegt vor ODER positiver SRK-Pre-Check.

Ärztinnen/Ärzte:
- Gesuchte Fachrichtungen: {", ".join(PHYSICIAN_SPECIALTIES)}
- Von Vorteil: MEBEKO-Anerkennung oder positiver Stand des Anerkennungsverfahrens.
- Deutsch: mindestens B2, für Ärzte idealerweise C1.
""".strip()
