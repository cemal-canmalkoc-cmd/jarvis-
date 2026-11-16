"""WhatsApp-Ansprache: personalisierte Nachricht + Klick-Link (wa.me).

Jarvis verschickt NICHT selbst. Du klickst den Link, WhatsApp öffnet sich mit
fertigem Text, du drückst Senden. Das hält deinen WhatsApp-Account sicher
(keine Sperre wegen Massenversand) und ist datenschutzrechtlich sauber.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from .config import AGENCY_NAME, RECRUITER_NAME
from .models import Assessment


def normalize_phone(raw: str | None, default_country: str = "41") -> str | None:
    """Wandelt Nummern in das wa.me-Format (nur Ziffern, mit Ländervorwahl)."""
    if not raw:
        return None
    s = raw.strip()
    plus = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    elif not plus:
        if digits.startswith("0"):
            digits = default_country + digits[1:]
    if len(digits) < 9 or len(digits) > 15:
        return None
    return digits


def build_message(a: Assessment) -> str:
    first = a.full_name.split()[0] if a.full_name else ""
    greeting = f"Grüezi {first}" if first else "Grüezi"

    if a.category == "arzt":
        role = f"Ärztin/Arzt {a.physician_specialty}" if a.physician_specialty else "Ärztin/Arzt"
        hook = "Wir haben aktuell mehrere offene Stellen in Schweizer Kliniken"
        if a.recognition_status in ("anerkannt", "positiver_precheck"):
            hook += ", und Ihr MEBEKO-Stand passt sehr gut"
    else:
        role = a.nursing_field or "Pflegefachperson"
        hook = "Wir haben aktuell spannende Stellen in Schweizer Spitälern und Institutionen"
        if a.recognition_status in ("anerkannt", "positiver_precheck"):
            hook += " – mit Ihrer SRK-Anerkennung können Sie direkt starten"

    return (
        f"{greeting}, hier ist {RECRUITER_NAME} von {AGENCY_NAME}. "
        f"Ich bin auf Ihr Profil als {role} aufmerksam geworden. "
        f"{hook}. "
        "Hätten Sie diese Woche kurz 10 Minuten für ein unverbindliches Gespräch? "
        "Falls kein Interesse besteht, genügt ein kurzes Nein – dann melde ich mich nicht mehr."
    )


def build_link(phone: str | None, message: str) -> str | None:
    num = normalize_phone(phone)
    if not num:
        return None
    return f"https://wa.me/{num}?text={quote(message)}"
