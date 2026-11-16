"""Vermittlungshonorare von Hansa Personal.

Die Preise legst DU fest (per WhatsApp: „Pflege: 18 % vom Jahreslohn, 3 Monate Garantie").
Solange für einen Bereich nichts hinterlegt ist, nennt Jarvis keinen Preis, sondern verweist
auf ein persönliches Angebot – er erfindet nie Konditionen.
"""
from __future__ import annotations

from . import config, store


def area_for(category: str, role: str | None) -> str:
    if category == "arzt":
        return "Arzt"
    r = (role or "").lower()
    if "fage" in r or "fachperson gesundheit" in r or "fachfrau gesundheit" in r or "fachmann gesundheit" in r:
        return "FaGe"
    return "Pflege"


def describe(row) -> str:
    if row["modell"] == "prozent_jahreslohn":
        price = f"{row['wert']:g} % des vereinbarten Bruttojahreslohns"
    else:
        price = f"CHF {row['wert']:,.0f}".replace(",", "'") + " pauschal"
    text = f"{price}, fällig erst bei erfolgreicher Anstellung (Erfolgshonorar)"
    if row["garantie_monate"]:
        text += f"; {row['garantie_monate']} Monate Ersatzgarantie"
    if row["notiz"]:
        text += f"; {row['notiz']}"
    return text


def overview() -> dict[str, str]:
    prices = store.get_prices(store.connect())
    return {a: (describe(prices[a]) if a in prices else "noch nicht festgelegt") for a in store.PRICE_AREAS}


def for_candidate(category: str, role: str | None) -> str | None:
    row = store.get_prices(store.connect()).get(area_for(category, role))
    return describe(row) if row else None


def phone_text() -> str:
    """Abschnitt für den Telefon-Leitfaden bei Arbeitgebern."""
    prices = store.get_prices(store.connect())
    if not prices:
        return (f"Konditionen: Nenne KEINE Preise. Sage, dass {config.RECRUITER_NAME} gern ein individuelles "
                "Angebot per E-Mail schickt, und frage nach der E-Mail-Adresse. Erwähne, dass nur bei "
                "erfolgreicher Anstellung etwas kostet.")
    lines = [f"- {a}: {describe(prices[a])}" for a in store.PRICE_AREAS if a in prices]
    return ("Konditionen (nur nennen, wenn danach gefragt wird; nichts anderes versprechen, keine Rabatte):\n"
            + "\n".join(lines)
            + f"\nFür Bereiche ohne Eintrag: individuelles Angebot durch {config.RECRUITER_NAME}.")
