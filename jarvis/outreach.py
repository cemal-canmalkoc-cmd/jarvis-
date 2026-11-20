"""Headhunter-Ansprache: Jarvis schreibt gefundene Kandidaten selbst an und lädt sie ein,
sich per WhatsApp bei Cemal-Can zu melden (oder sich im Formular zu bewerben).

Regeln (fest eingebaut):
- Nur Personen, die selbst öffentlich ein Stellengesuch mit E-Mail-Adresse veröffentlicht haben.
- Jede Adresse höchstens EINMAL, mit Abmelde-Hinweis; Sperrliste wird beachtet.
- Nur passende Profile (nicht Tier X).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from . import config, store
from .models import ScoredCandidate
from .whatsapp import role_phrase

log = logging.getLogger("jarvis.outreach")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def contact_number() -> str:
    return config.CONTACT_WHATSAPP or config.JARVIS_WHATSAPP_NUMBER


def wa_link(text: str = "") -> str:
    num = "".join(ch for ch in contact_number() if ch.isdigit())
    return f"https://wa.me/{num}" + (f"?text={quote(text)}" if text else "")


def can_email() -> bool:
    from .matching import smtp_host
    return bool(smtp_host() and config.SMTP_USER and config.SMTP_PASSWORD)


def build_email(c: ScoredCandidate) -> tuple[str, str]:
    a = c.assessment
    first = a.full_name.split()[0] if a.full_name and a.full_name.lower() not in ("unbekannt", "") else ""
    greeting = f"Guten Tag {first}" if first else "Guten Tag"
    role = role_phrase(a)
    hello = f"Hallo, ich habe Ihr Stellengesuch gesehen ({role}). Gerne mehr Infos zur Schweiz."
    rec = ("Ihre SRK-Anerkennung" if a.category == "pflege" else "Ihr MEBEKO-Stand") \
        if a.recognition_status in ("anerkannt", "positiver_precheck") else None
    subject = f"Ihr Stellengesuch als {role} – Stellen in der Schweiz"
    body = f"""{greeting}

ich bin auf Ihr Stellengesuch als {role} aufmerksam geworden. Ich bin {config.RECRUITER_NAME} von
{config.AGENCY_NAME} – wir vermitteln Pflegefachpersonen und Ärztinnen/Ärzte an Spitäler, Kliniken
und Heime in der Schweiz. Für Sie ist das komplett kostenlos.
{f"{rec} ist dabei ein grosser Vorteil." if rec else ""}
Wenn Sie Interesse haben, schreiben Sie mir einfach kurz per WhatsApp:
{wa_link(hello)}
({contact_number()})

Oder bewerben Sie sich in 2 Minuten online: {config.PUBLIC_URL}/bewerbung

Freundliche Grüsse
{config.RECRUITER_NAME}
{config.AGENCY_NAME}

Sie möchten keine weiteren Nachrichten? Antworten Sie einfach mit „STOP" – wir melden uns dann nicht mehr."""
    return subject, body.replace("\n\n\n", "\n\n")


def reach_out(c: ScoredCandidate) -> str:
    """Einmalige E-Mail an einen gefundenen Kandidaten. Gibt einen Status zurück."""
    email = (c.assessment.email or "").strip()
    if c.tier == "X":
        return "ungeeignet"
    if not EMAIL_RE.match(email):
        return "keine_email"
    conn = store.connect()
    key = f"mailed:{email.lower()}"
    if store.get_state(conn, key) or store.is_opted_out(conn, c.assessment.phone):
        return "schon_kontaktiert"
    if not can_email():
        return "email_nicht_eingerichtet"
    from .matching import send_email
    subject, body = build_email(c)
    send_email(email, subject, body)
    store.set_state(conn, key, "1")
    store.set_status(conn, store.candidate_key(c), "kontaktiert", f"E-Mail mit WhatsApp-Link an {email}")
    return "gesendet"
