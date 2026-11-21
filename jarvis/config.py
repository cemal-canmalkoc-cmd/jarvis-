"""Suchprofil und Einstellungen von Jarvis.

Hier wird festgelegt, WEN Jarvis sucht. Änderungen am Bedarf nur hier pflegen.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

BASE_DIR = Path(os.environ.get("JARVIS_HOME", Path(__file__).resolve().parent.parent))

# .env-Datei laden (einfache KEY=VALUE-Zeilen), ohne bestehende Variablen zu überschreiben
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            _v = _v.split(" #", 1)[0]  # Kommentar am Zeilenende ignorieren
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())
DATA_DIR = BASE_DIR / "data"
INBOX_DIR = DATA_DIR / "inbox"          # Lebensläufe (PDF/DOCX/TXT) hier ablegen
PROCESSED_DIR = DATA_DIR / "processed"  # verarbeitete Dateien landen hier
REPORT_DIR = BASE_DIR / "reports"       # tägliche Shortlists (HTML + CSV)
DB_PATH = DATA_DIR / "jarvis.sqlite3"

# Sparmodus (Standard): Claude Haiku 5.5 – rund 40x günstiger als Opus, für Lebensläufe,
# Chats und Telefonate gut geeignet. Für maximale Qualität: JARVIS_SPARMODUS=0 (Claude Opus 5.5).
SPARMODUS = os.environ.get("JARVIS_SPARMODUS", "1").strip().lower() not in ("0", "false", "nein")
MODEL = os.environ.get("JARVIS_MODEL", "claude-haiku-5-5" if SPARMODUS else "claude-opus-5-5")
EFFORT = os.environ.get("JARVIS_EFFORT", "low" if SPARMODUS else "medium")
WEB_SEARCHES_PER_FOCUS = int(os.environ.get("JARVIS_WEB_SEARCHES", "3" if SPARMODUS else "8"))

# Absender-Angaben für die WhatsApp-Nachrichten
RECRUITER_NAME = os.environ.get("JARVIS_RECRUITER_NAME", "Cemal-Can Malkoc")
AGENCY_NAME = os.environ.get("JARVIS_AGENCY_NAME", "Hansa Personal")

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

# Bewerbungsformular: deutsche Berufsbezeichnung → ungefähre offizielle Bezeichnung in der Schweiz.
# Die verbindliche Einstufung entscheidet die Anerkennungsstelle (SRK, MEBEKO bzw. SBFI).
MEDICAL_ROLES = {
    "Pflege (mit Diplom/Examen)": [
        "Gesundheits- und Krankenpfleger/in / Krankenschwester → CH: Dipl. Pflegefachfrau/-mann HF",
        "Pflegefachfrau/-mann (Generalistik) → CH: Dipl. Pflegefachfrau/-mann HF",
        "Pflege mit Bachelor (B.Sc.) → CH: Pflegefachfrau/-mann FH",
        "Gesundheits- und Kinderkrankenpfleger/in → CH: Dipl. Pflegefachperson HF (Pädiatrie)",
        "Altenpfleger/in (examiniert) → CH: je nach SRK-Entscheid Pflegefachperson HF oder FaGe",
        "Psychiatrische Pflege → CH: Dipl. Pflegefachperson HF Psychiatrie",
        "Fachkrankenpflege Intensiv → CH: Dipl. Expert/in Intensivpflege NDS HF",
        "Fachkrankenpflege Anästhesie → CH: Dipl. Expert/in Anästhesiepflege NDS HF",
        "Fachkrankenpflege Notfall → CH: Dipl. Expert/in Notfallpflege NDS HF",
        "OP-Pflege / OTA → CH: Dipl. Fachfrau/-mann Operationstechnik HF",
    ],
    "Pflegeassistenz & Betreuung": [
        "FaGe (Fachfrau/Fachmann Gesundheit EFZ)",
        "Pflegehelfer/in, Pflegeassistenz → CH: Pflegehelfer/in SRK bzw. Assistent/in Gesundheit und Soziales (AGS)",
        "Betreuungskraft / 24-Stunden-Betreuung (Live-in)",
    ],
    "Ärztin / Arzt": [f"Ärztin/Arzt {s}" for s in ("Allgemeine Innere Medizin", "Psychiatrie", "Gynäkologie",
                                                  "Radiologie", "Anästhesie", "Geriatrie", "Neurologie",
                                                  "Rehabilitation", "Chirurgie", "Pädiatrie", "Notfallmedizin",
                                                  "Allgemeinmedizin / Hausarzt", "andere Fachrichtung")]
                       + ["Assistenzärztin/-arzt (in Weiterbildung)", "Oberärztin/Oberarzt"],
    "Weitere medizinische Berufe": [
        "Medizinische Fachangestellte (MFA) → CH: Medizinische Praxisassistentin MPA",
        "MTRA → CH: Fachfrau/-mann für medizinisch-technische Radiologie HF",
        "Notfallsanitäter/in → CH: Dipl. Rettungssanitäter/in HF",
        "Hebamme → CH: Hebamme FH",
        "Physiotherapeut/in → CH: Physiotherapeut/in FH",
        "Ergotherapeut/in → CH: Ergotherapeut/in FH",
    ],
}

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

24-Stunden-/Live-in-Betreuung (Seniorenbetreuung zu Hause):
- Betreuungskräfte, Pflegehelfer/innen, Altenpfleger/innen; Erfahrung in der Betreuung, Deutsch mind. B1.

GESCHÄFTSMODELL SCHWEIZ (Partner-Modell):
- Hansa Personal gewinnt medizinisches Personal in Deutschland (Ärzte, Pflegefachkräfte, FaGe, Betreuungskräfte).
- Schweizer Partner (Kliniken, Spitex, Personalvermittler/-verleiher mit Bewilligung, 24h-Betreuungsanbieter)
  stellen an und übernehmen Anstellung, Bewilligungen und Abwicklung.
- Hansa Personal erhält dafür eine Provision (Erfolgshonorar) vom Partner – für Bewerber ist alles kostenlos.
""".strip()

# ---------------------------------------------------------------------------
# Autopilot, Telefonie, WhatsApp
# ---------------------------------------------------------------------------
def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "ja", "yes")


TIMEZONE = os.environ.get("JARVIS_TIMEZONE", "Europe/Zurich")
# Tagesgrenzen (Budget, „heute“) in deiner Zeitzone statt Server-Zeit (UTC)
if hasattr(time, "tzset"):
    # POSIX-Regel funktioniert auch ohne Zeitzonen-Dateien im Container (Mitteleuropa: MEZ/MESZ)
    os.environ["TZ"] = ("CET-1CEST,M3.5.0,M10.5.0/3"
                        if TIMEZONE in ("Europe/Zurich", "Europe/Berlin", "Europe/Vienna") else TIMEZONE)
    time.tzset()
DAILY_TARGET = int(os.environ.get("JARVIS_DAILY_TARGET", "20"))  # Ziel: vermittelbare Kandidaten/Tag
MORNING_HOUR = int(os.environ.get("JARVIS_MORNING_HOUR", "7"))
CALL_HOURS = (9, 18)               # Anrufe nur Mo-Fr in diesem Fenster (lokale Zeit)
MAX_CALLS_PER_ROUND = int(os.environ.get("JARVIS_MAX_CALLS_PER_ROUND", "5"))
AUTO_CALL_CANDIDATES = _flag("JARVIS_AUTO_CALL_CANDIDATES", "1")
AUTO_CALL_COMPANIES = _flag("JARVIS_AUTO_CALL_COMPANIES", "0")  # Arbeitgeber betreut der Partner-Vermittler

PUBLIC_URL = os.environ.get("JARVIS_PUBLIC_URL", "http://localhost:8000").rstrip("/")
OWNER_WHATSAPP = os.environ.get("JARVIS_OWNER_WHATSAPP", "")    # deine Nummer, z.B. +49176...
ADMIN_TOKEN = os.environ.get("JARVIS_ADMIN_TOKEN", "")          # schützt das Dashboard

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # Jarvis' WhatsApp-Nummer, +41...
TWILIO_VOICE_FROM = os.environ.get("TWILIO_VOICE_FROM", "")        # Jarvis' Telefonnummer
TWILIO_TEMPLATE_FIRST_CONTACT = os.environ.get("TWILIO_TEMPLATE_FIRST_CONTACT", "")  # Content-SID
VALIDATE_TWILIO = _flag("JARVIS_VALIDATE_TWILIO", "1")

VOICE_LANGUAGE = os.environ.get("JARVIS_VOICE_LANGUAGE", "de-DE")
VOICE_TTS_PROVIDER = os.environ.get("JARVIS_VOICE_TTS_PROVIDER", "")  # z.B. ElevenLabs
VOICE_NAME = os.environ.get("JARVIS_VOICE_NAME", "")
VOICE_EFFORT = os.environ.get("JARVIS_VOICE_EFFORT", "low")       # niedrige Latenz am Telefon
VOICE_FAST_MODE = _flag("JARVIS_VOICE_FAST_MODE", "0")            # schnellere Antworten, doppelter Preis

# ---------------------------------------------------------------------------
# WhatsApp-Anbieter: "meta" (Standard, direkt & am günstigsten) oder "twilio"
# ---------------------------------------------------------------------------
WHATSAPP_PROVIDER = os.environ.get("JARVIS_WHATSAPP_PROVIDER", "meta").strip().lower()
META_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "")            # dauerhaftes System-User-Token
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "")  # ID der WhatsApp-Nummer
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")            # prüft, dass Webhooks echt sind
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")        # frei wählbar, für die Webhook-Einrichtung
META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")
META_TEMPLATE_FIRST_CONTACT = os.environ.get("META_TEMPLATE_FIRST_CONTACT", "")  # Name der Vorlage
META_TEMPLATE_LANG = os.environ.get("META_TEMPLATE_LANG", "de")
JARVIS_WHATSAPP_NUMBER = os.environ.get("JARVIS_WHATSAPP_NUMBER", "")  # Jarvis' Nummer (für wa.me-Links)

# ---------------------------------------------------------------------------
# E-Mail (kostenlos über dein bestehendes Postfach): Kandidatenprofile an Kliniken senden
# ---------------------------------------------------------------------------
SMTP_HOST = os.environ.get("JARVIS_SMTP_HOST", "")  # leer = automatisch aus dem Login erkennen
SMTP_PORT = int(os.environ.get("JARVIS_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("JARVIS_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("JARVIS_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("JARVIS_SMTP_FROM", "")

# Bestandskunden automatisch beliefern (anonyme Vorstellung per E-Mail, sobald ein passender
# Kandidat Interesse bestätigt hat). 0 = nur auf deinen Befehl.
AUTO_DELIVER = _flag("JARVIS_AUTO_DELIVER", "1")

# Öffentliche Rufnummer von Hansa Personal für Kandidaten & Kliniken. Anrufe darauf werden zu
# Jarvis umgeleitet (siehe README „Anrufe annehmen"). Steht in Nachrichten, Formular und Inseraten.
CALL_IN_NUMBER = os.environ.get("JARVIS_CALL_IN_NUMBER", "")

# Falls deine WhatsApp-Nummer gleichzeitig Jarvis' Nummer ist, kommen Meldungen per E-Mail + App.
OWNER_EMAIL = os.environ.get("JARVIS_OWNER_EMAIL", "")

# Suche über den Tag: alle N Stunden (zwischen 8 und 21 Uhr) eine kleine Suchrunde mit
# wechselnden Bereichen und Regionen. 0 = nur morgens. Kosten: ca. 0.20–0.30 $ pro Runde.
SEARCH_EVERY_HOURS = int(os.environ.get("JARVIS_SEARCH_EVERY_HOURS", "2"))
SEARCH_HOURS = (8, 21)

# Inserate: Jarvis schreibt täglich Inserate und postet sie auf eurer Facebook-Seite.
ADS_PER_DAY = int(os.environ.get("JARVIS_ADS_PER_DAY", "0"))  # Marketing aus (Wunsch des Inhabers)
META_PAGE_ID = os.environ.get("META_PAGE_ID", "")        # ID der Facebook-Seite "Hansa Personal"
META_PAGE_TOKEN = os.environ.get("META_PAGE_TOKEN", "")  # dauerhaftes Seiten-Token (pages_manage_posts)

# Deine WhatsApp-Nummer, über die sich Kandidaten bei dir melden (Inserate, E-Mails, Formular).
CONTACT_WHATSAPP = os.environ.get("JARVIS_CONTACT_WHATSAPP", "")

# Jarvis ruft DICH an, wenn er gute Kandidaten gefunden hat (Twilio nötig). Max. Anrufe pro Tag.
OWNER_PHONE = os.environ.get("JARVIS_OWNER_PHONE", "")
OWNER_CALLS_PER_DAY = int(os.environ.get("JARVIS_OWNER_CALLS_PER_DAY", "3"))

# Ausgaben: automatisches Tagesbudget in $ für Arbeit, die Jarvis von SICH AUS startet
# (Suchrunden, Inserate). 0 = nichts automatisch, Jarvis fragt stattdessen. Befehle von dir laufen immer.
DAILY_BUDGET_USD = float(os.environ.get("JARVIS_DAILY_BUDGET_USD", "1.0"))  # Gesamtgrenze pro Tag

# Tagesminimum: Jarvis sucht so lange (in mehreren Runden, mit wechselnden Berufen/Portalen),
# bis mindestens so viele NEUE potenzielle Kandidaten (Tier A/B/C) gefunden sind – höchstens bis
# MINIMUM_MAX_USD pro Tag. Zeiten: 9, 13 und 17 Uhr.
DAILY_MINIMUM = int(os.environ.get("JARVIS_DAILY_MINIMUM", "1"))
MINIMUM_MAX_USD = float(os.environ.get("JARVIS_MINIMUM_MAX_USD", "0.30"))

# ---------------------------------------------------------------------------
# Zweiter Bereich: LKW-Fahrer in Deutschland (an Speditionen/Logistik vermitteln)
# ---------------------------------------------------------------------------
LKW_ENABLED = os.environ.get("JARVIS_LKW", "1").strip().lower() not in ("0", "false", "nein")
LKW_REQUIREMENTS_TEXT = """BEDARF DEUTSCHLAND: Berufskraftfahrer/innen (LKW)
- Pflicht: Führerschein Klasse C oder CE (CE bevorzugt), gültige Fahrerkarte,
  Schlüsselzahl 95 / Modul 95 (Berufskraftfahrerqualifikation, BKrFQG).
- Von Vorteil: ADR-Schein (Gefahrgut), Erfahrung im Nah- oder Fernverkehr, Kran/Stapler,
  Deutsch mind. B1 (für Kundenkontakt), Wohnort in Deutschland oder EU.
- Für Fahrer ist die Vermittlung kostenlos."""

# Umsatzsteuer-Status deines Einzelunternehmens: "unklar" | "kleinunternehmer" | "regel"
UST_STATUS = os.environ.get("JARVIS_UST_STATUS", "unklar")

# Monatsziel Umsatz in €
REVENUE_GOAL = float(os.environ.get("JARVIS_REVENUE_GOAL", "25000"))

# Bewerbungen auf Stellenanzeigen: 0 = nur mit deiner Freigabe in der App (empfohlen), 1 = automatisch
AUTO_APPLY = os.environ.get("JARVIS_AUTO_APPLY", "1").strip().lower() in ("1", "true", "ja")
AUTO_APPLY_PER_DAY = int(os.environ.get("JARVIS_AUTO_APPLY_PER_DAY", "10"))

# Rechnungsdaten (Pflichtangaben § 14 UStG) – in der App unter ⚙️ eintragen
FIRMA_ADRESSE = os.environ.get("JARVIS_FIRMA_ADRESSE", "")   # z.B. "Musterstr. 1, 12345 Musterstadt"
STEUERNUMMER = os.environ.get("JARVIS_STEUERNUMMER", "")
IBAN = os.environ.get("JARVIS_IBAN", "")
BANK = os.environ.get("JARVIS_BANK", "")
# Rechnung am Starttag automatisch senden (1) oder erst nach deinem Tipp (0)
AUTO_INVOICE = os.environ.get("JARVIS_AUTO_INVOICE", "0").strip().lower() in ("1", "true", "ja")


# --------------------------------------------------------------------------- Selbstständiger Betrieb
# Gespräche mit Bewerbern und Firmen führt die KI selbst – höchstens CHAT_MAX_USD pro Tag und nur,
# solange die Freigabe läuft (AUTO_DAYS Tage; danach in der App auf „Weiter" tippen).
CHAT_MAX_USD = float(os.environ.get("JARVIS_CHAT_MAX_USD", "0.20"))
AUTO_DAYS = int(os.environ.get("JARVIS_AUTO_DAYS", "5"))
# Jeden Tag fragen: ohne dein „Ja“ in der App gibt Jarvis an dem Tag nichts automatisch aus
# Empfehlungsprämie (Text, z. B. "100 €") – leer = keine Prämie anzeigen
REFERRAL_BONUS = os.environ.get("JARVIS_REFERRAL_BONUS", "")            # alt: für alle Bereiche
REFERRAL_BONUS_LKW = os.environ.get("JARVIS_REFERRAL_BONUS_LKW", "200 €")
REFERRAL_BONUS_PFLEGE = os.environ.get("JARVIS_REFERRAL_BONUS_PFLEGE", "1.000 €")
REFERRAL_BONUS_ARZT = os.environ.get("JARVIS_REFERRAL_BONUS_ARZT", "2.000 €")
# Ohne verbundenes Postfach: E-Mails landen im Postausgang der App und gehen per 1 Tipp über deine Mail-App raus
OUTBOX = os.environ.get("JARVIS_OUTBOX", "1").strip().lower() in ("1", "true", "ja")
# Täglich so viele Firmen mit offener Stelle per E-Mail anschreiben (kostenlos, ohne Tages-Ja)
ACQUISITION_PER_DAY = int(os.environ.get("JARVIS_ACQUISITION_PER_DAY", "10"))
# Marketing-Funktion (Inserate schreiben, Facebook-Posts, Team „Marketing“) – aus
MARKETING = os.environ.get("JARVIS_MARKETING", "0").strip().lower() in ("1", "true", "ja")
ASK_DAILY = os.environ.get("JARVIS_ASK_DAILY", "1").strip().lower() in ("1", "true", "ja")
# Postfach lesen und beantworten (gleiche Zugangsdaten wie der E-Mail-Versand)
AUTO_INBOX = os.environ.get("JARVIS_AUTO_INBOX", "1").strip().lower() in ("1", "true", "ja")
IMAP_HOST = os.environ.get("JARVIS_IMAP_HOST", "")
# Outlook: App-ID aus der Microsoft-App-Registrierung (für „Mit Microsoft anmelden“)
MS_CLIENT_ID = os.environ.get("JARVIS_MS_CLIENT_ID", "")
# Bewerber-Links (/wa?b=…) führen zum KI-Chat statt in dein WhatsApp (1 = ja)
CHAT_FIRST = os.environ.get("JARVIS_CHAT_FIRST", "0").strip().lower() in ("1", "true", "ja")
