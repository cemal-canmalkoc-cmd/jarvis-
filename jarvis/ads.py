"""Inserate: Jarvis schreibt täglich neue Inserate und postet sie selbst auf eurer Facebook-Seite.

- Facebook-SEITE (Hansa Personal): automatisch über die Meta Graph API (META_PAGE_ID + META_PAGE_TOKEN).
- Facebook-GRUPPEN, Kleinanzeigen, Indeed: automatisches Posten ist dort verboten (Kontosperre).
  Dafür landen fertige Texte als Meldung in der App – kopieren, posten, fertig.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import requests

from . import brain, config, messaging, store
from .config import NURSING_FIELDS, PHYSICIAN_SPECIALTIES

log = logging.getLogger("jarvis.ads")

TARGETS = [
    "Dipl. Pflegefachpersonen aus Deutschland, die in die Schweiz wollen",
    "Pflegefachkräfte Psychiatrie",
    "FaGe / Fachpersonen Gesundheit",
    "Pflegefachkräfte Geriatrie und Langzeitpflege",
    "Pflegefachkräfte Akutspital",
    "Ärztinnen und Ärzte (alle gesuchten Fachrichtungen)",
    "Pflegekräfte, die bereits in der Schweiz leben und wechseln wollen",
    "Pflegefachkräfte mit SRK-Anerkennung",
]
EMPLOYER_TARGETS = [
    "ARBEITGEBER: Speditionen und Logistikfirmen, die LKW-Fahrer CE suchen",
]
LKW_TARGETS = [
    "LKW-Fahrer CE Fernverkehr (Deutschland)",
    "Berufskraftfahrer CE Nahverkehr – abends zu Hause",
    "LKW-Fahrer mit ADR-Schein",
    "Kraftfahrer C/CE für Baustelle und Kipper",
]

AD_SYSTEM = f"""Du schreibst Stelleninserate für {config.AGENCY_NAME}, eine Personalvermittlung für
Gesundheitsfachpersonen in die Schweiz. Ton: warm, klar, seriös, Sie- oder Du-Form passend zur Plattform.

Gesucht werden: {", ".join(NURSING_FIELDS)}; Ärztinnen/Ärzte in {", ".join(PHYSICIAN_SPECIALTIES)}.
Voraussetzungen Pflege: Diplom/Examen + Deutsch B2 (Ausland: SRK-Anerkennung, wir helfen dabei).
Ärzte: MEBEKO-Anerkennung von Vorteil, wir begleiten das Verfahren.
Für Bewerber ist die Vermittlung kostenlos.

Regeln:
- Keine erfundenen Lohnzahlen, keine konkreten Arbeitgebernamen, keine Garantien.
- Immer die Kontaktwege nennen: WhatsApp {config.PUBLIC_URL}/wa?b=pflege und Formular {config.PUBLIC_URL}/bewerbung{" und Telefon " + config.CALL_IN_NUMBER if config.CALL_IN_NUMBER else ""}.
- 3–6 Emojis sparsam, kurze Absätze, maximal ca. 120 Wörter, am Ende 3–5 passende Hashtags.
- Gib NUR den fertigen Inseratstext aus, ohne Vorbemerkung."""


LKW_AD_SYSTEM = f"""Du schreibst Stelleninserate für {config.AGENCY_NAME}, eine Personalvermittlung für
LKW-Fahrer in Deutschland. Ton: direkt, ehrlich, auf Augenhöhe, Du-Form.

{config.LKW_REQUIREMENTS_TEXT}

Regeln:
- Keine erfundenen Löhne, keine Firmennamen, keine Garantien.
- Kontaktwege: WhatsApp {config.PUBLIC_URL}/wa?b=lkw und Formular {config.PUBLIC_URL}/bewerbung?bereich=lkw
- 3–5 Emojis, kurze Absätze, max. ca. 100 Wörter, am Ende 3–5 Hashtags.
- Gib NUR den fertigen Text aus."""


EMPLOYER_AD_SYSTEM = f"""Du schreibst Beiträge für {config.AGENCY_NAME} an ARBEITGEBER (Speditionen, Logistik,
Kliniken). Botschaft: geprüfte LKW-Fahrer (C/CE, Modul 95, ADR) bzw. Pflegekräfte, kurzfristig verfügbar,
Bezahlung nur bei Einstellung, keine Vorabkosten. Seriös, kurz (max. 90 Wörter), 2–3 Emojis, Hashtags.
Kontakt: {config.PUBLIC_URL}/firmen und WhatsApp {config.PUBLIC_URL}/wa?b=firma. Keine erfundenen Zahlen.
Gib NUR den fertigen Text aus."""


def _system(lkw: bool = False, employer: bool = False) -> str:
    if employer:
        return EMPLOYER_AD_SYSTEM
    from .outreach import contact_number
    return (LKW_AD_SYSTEM if lkw else AD_SYSTEM).replace("{wa}", contact_number() or "(keine)")


def target_for_today(offset: int = 0) -> str:
    pool = TARGETS + (LKW_TARGETS + EMPLOYER_TARGETS if config.LKW_ENABLED else [])
    return pool[(date.today().toordinal() * 2 + offset) % len(pool)]


def write_ad(target: str | None = None, platform: str = "Facebook") -> str:
    target = target or target_for_today()
    lkw = any(w in target.lower() for w in ("lkw", "fahrer", "kraftfahrer"))
    employer = target.upper().startswith("ARBEITGEBER")
    resp = brain.create(
        model=config.MODEL, max_tokens=2000, system=_system(lkw, employer), output_config={"effort": "low"},
        messages=[{"role": "user", "content": f"Plattform: {platform}. Zielgruppe: {target}. "
                                              f"Schreib ein neues, abwechslungsreiches Inserat (Datum {date.today()})."}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def facebook_ready() -> bool:
    return bool(config.META_PAGE_ID and config.META_PAGE_TOKEN)


def post_facebook_page(text: str) -> str:
    """Postet auf die eigene Facebook-Seite. Gibt die Beitrags-ID zurück."""
    r = requests.post(f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/{config.META_PAGE_ID}/feed",
                      data={"message": text, "link": f"{config.PUBLIC_URL}/bewerbung",
                            "access_token": config.META_PAGE_TOKEN}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Facebook-Fehler {r.status_code}: {r.text[:300]}")
    return r.json().get("id", "")


def daily_round(offset: int = 0) -> dict:
    """Ein Inserat schreiben und veröffentlichen (Facebook-Seite) + Gruppen-Text als Meldung."""
    target = target_for_today(offset)
    text = write_ad(target, "Facebook")
    out: dict = {"zielgruppe": target, "facebook_seite": None}
    if facebook_ready():
        try:
            out["facebook_seite"] = post_facebook_page(text)
        except Exception as exc:  # noqa: BLE001
            log.error("Facebook-Post fehlgeschlagen: %s", exc)
            out["fehler"] = str(exc)
    group_text = write_ad(target, "Facebook-Gruppe (persönlicher, kürzer)")
    store.set_state(store.connect(), f"ad:{date.today()}:{offset}", group_text)
    posted = "✅ Auf eurer Facebook-Seite gepostet.\n\n" if out.get("facebook_seite") else ""
    messaging.notify_owner(
        f"📣 Inserat des Tages ({target})\n{posted}"
        f"Für Facebook-Gruppen kopieren und posten (2 Min.):\n\n{group_text}")
    out["gruppen_text"] = group_text
    return out


def due_slots(now: datetime) -> list[int]:
    """Posting-Zeiten: 10 Uhr (+ 18 Uhr bei 2 pro Tag)."""
    hours = [10, 18][: max(0, min(config.ADS_PER_DAY, 2))]
    return [i for i, h in enumerate(hours) if now.hour >= h]
