"""Regelbasierte Bewertung nach euren Kriterien.

Claude liest nur Fakten aus; die Entscheidung, wer passt, ist hier transparent
im Code und damit nachvollziehbar und anpassbar.
"""
from __future__ import annotations

from .config import NURSING_FIELDS, PHYSICIAN_SPECIALTIES
from .models import Assessment

GERMAN_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "muttersprache": 7}


def _matches(value: str | None, options: list[str]) -> bool:
    if not value:
        return False
    v = value.lower()
    for opt in options:
        for token in opt.lower().replace("/", " ").replace("(", " ").replace(")", " ").split():
            if len(token) >= 4 and token in v:
                return True
    return False


def score(a: Assessment) -> tuple[int, str, list[str], list[str]]:
    """Gibt (score, tier, reasons, missing) zurück."""
    reasons: list[str] = []
    missing: list[str] = []
    pts = 0
    knockout = False

    german = GERMAN_RANK.get(a.german_level, 0)

    if a.category == "pflege":
        if a.nursing_field:
            pts += 15
            reasons.append(f"Pflegebereich: {a.nursing_field}")
        if a.has_diploma_certificate:
            pts += 20
            reasons.append("Urkunde/Diplom vorhanden")
        elif a.has_diploma_certificate is False:
            knockout = True
            reasons.append("Keine Urkunde – Pflichtkriterium nicht erfüllt")
        else:
            missing.append("Diplom/Urkunde bestätigen lassen")

        if german >= GERMAN_RANK["B2"]:
            pts += 20
            reasons.append(f"Deutsch {a.german_level}")
        elif german:
            knockout = True
            reasons.append(f"Deutsch nur {a.german_level} – B2 erforderlich")
        else:
            missing.append("Deutschniveau (mind. B2) nachweisen")

        rec = a.recognition_status
        if rec == "anerkannt":
            pts += 35
            reasons.append("SRK-Anerkennung liegt vor ⭐")
        elif rec == "positiver_precheck":
            pts += 30
            reasons.append("Positiver SRK-Pre-Check ⭐")
        elif rec == "nicht_noetig":
            pts += 35
            reasons.append("Schweizer Diplom – keine Anerkennung nötig")
        elif rec == "laufend":
            pts += 15
            reasons.append("SRK-Verfahren läuft")
        elif rec == "fehlt":
            pts += 0
            missing.append("SRK-Anerkennung beantragen (Pre-Check)")
        else:
            missing.append("SRK-Status klären")

    elif a.category == "arzt":
        if _matches(a.physician_specialty, PHYSICIAN_SPECIALTIES):
            pts += 30
            reasons.append(f"Gesuchte Fachrichtung: {a.physician_specialty}")
        else:
            pts += 5
            reasons.append(f"Fachrichtung nicht im Bedarf: {a.physician_specialty or 'unbekannt'}")

        rec = a.recognition_status
        if rec in ("anerkannt", "nicht_noetig"):
            pts += 35
            reasons.append("MEBEKO-Anerkennung / CH-Diplom ⭐")
        elif rec == "positiver_precheck":
            pts += 28
            reasons.append("Positiver MEBEKO-Verfahrensstand ⭐")
        elif rec == "laufend":
            pts += 15
            reasons.append("MEBEKO-Verfahren läuft")
        else:
            missing.append("MEBEKO-Status klären")

        if german >= GERMAN_RANK["C1"]:
            pts += 20
            reasons.append(f"Deutsch {a.german_level}")
        elif german >= GERMAN_RANK["B2"]:
            pts += 12
            reasons.append(f"Deutsch {a.german_level} (C1 ideal)")
        elif german:
            pts += 0
            missing.append(f"Deutsch {a.german_level} – mind. B2 nötig")
        else:
            missing.append("Deutschniveau klären")
    else:
        knockout = True
        reasons.append("Kein Pflege- oder Arztprofil")

    if a.currently_in_switzerland:
        pts += 10
        reasons.append("Ist aktuell in der Schweiz")
    if a.years_experience and a.years_experience >= 2:
        pts += 5
    if not a.phone:
        missing.append("Telefonnummer für WhatsApp fehlt")

    pts = min(pts, 100)
    if knockout:
        tier = "X"
    elif pts >= 75:
        tier = "A"
    elif pts >= 55:
        tier = "B"
    else:
        tier = "C"
    return pts, tier, reasons, missing
