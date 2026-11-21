"""Der Tagesablauf von Jarvis: sammeln → prüfen → bewerten → Shortlist."""
from __future__ import annotations

import logging

import anthropic

from . import brain, report, sources, store, whatsapp
from .config import DAILY_SHORTLIST_SIZE, NURSING_FIELDS, PHYSICIAN_SPECIALTIES
from .models import ScoredCandidate
from .scoring import score

log = logging.getLogger("jarvis")


def evaluate(raw: sources.RawProfile) -> ScoredCandidate:
    a = brain.extract(raw.text)
    pts, tier, reasons, missing = score(a)
    c = ScoredCandidate(assessment=a, source=raw.source, score=pts, tier=tier,
                        reasons=reasons, missing=missing,
                        consent_whatsapp=raw.consent_whatsapp, consent_call=raw.consent_call)
    if tier in ("A", "B", "C"):
        c.whatsapp_message = whatsapp.build_message(a)
        germany = a.category == "lkw" or "deutschland" in (a.current_location or "").lower()
        c.whatsapp_link = whatsapp.build_link(a.phone, c.whatsapp_message, "49" if germany else "41")
    return c


def default_web_focuses() -> list[str]:
    focuses = [f"Pflegefachperson {f}" for f in NURSING_FIELDS]
    focuses += [f"Arzt / Ärztin {s}" for s in PHYSICIAN_SPECIALTIES]
    from . import config
    if config.LKW_ENABLED:
        focuses += ["LKW: Berufskraftfahrer CE Fernverkehr", "LKW: LKW-Fahrer CE Nahverkehr",
                    "LKW: Fahrer sucht Arbeit mit Telefonnummer", "LKW: Kipperfahrer Baustelle sucht Stelle"]
    focuses += ["Pflegefachkraft sucht Stelle mit Telefonnummer"]
    return focuses


def run(use_folder: bool = True, use_email: bool = True, use_web: bool = False,
        web_focuses: list[str] | None = None) -> dict:
    conn = store.connect()
    raws: list[sources.RawProfile] = []
    if use_folder:
        raws += sources.from_inbox_folder()
    if use_email:
        try:
            raws += sources.from_email()
        except Exception as exc:  # Postfach-Probleme sollen den Lauf nicht stoppen
            log.error("E-Mail-Abruf fehlgeschlagen: %s", exc)
    if use_web:
        for focus in web_focuses or default_web_focuses():
            log.info("Web-Sourcing: %s", focus)
            try:
                for lead in brain.find_public_leads(focus):
                    raws.append(sources.RawProfile(source=lead.get("source_url", "web"),
                                                   text=lead["profile_text"]))
            except Exception as exc:  # noqa: BLE001 – ein Fokus darf die ganze Suche nie stoppen
                log.error("Web-Sourcing '%s' fehlgeschlagen: %s", focus, exc)

    stats = {"geprueft": 0, "neu": 0, "A": 0, "B": 0, "C": 0, "X": 0, "fehler": 0, "angeschrieben": 0}
    from . import outreach
    portal_leads = []
    for raw in raws:
        try:
            c = evaluate(raw)
        except (anthropic.APIError, RuntimeError, ValueError) as exc:
            log.error("Fehler bei %s: %s", raw.source, exc)
            stats["fehler"] += 1
            continue
        stats["geprueft"] += 1
        stats[c.tier] += 1
        if store.upsert(conn, c):
            stats["neu"] += 1
            if raw.source.startswith("http"):  # öffentliches Stellengesuch → Headhunter-Ansprache
                try:
                    status = outreach.reach_out(c)
                    if status == "gesendet":
                        stats["angeschrieben"] += 1
                    elif status in ("keine_email", "email_nicht_eingerichtet"):
                        portal_leads.append(c)
                except Exception as exc:  # noqa: BLE001
                    log.error("Ansprache %s fehlgeschlagen: %s", raw.source, exc)
        sources.archive(raw)
        log.info("%s → %s (%d)", c.assessment.full_name, c.tier, c.score)

    digest = outreach.portal_digest(portal_leads)
    if digest:
        from . import messaging
        messaging.notify_owner(digest)
    stats["portal_kontakte"] = len([c for c in portal_leads if c.tier != "X"])
    shortlist = store.todays_shortlist(conn, DAILY_SHORTLIST_SIZE)
    html_path, csv_path = report.write(shortlist)
    stats["shortlist"] = len(shortlist)
    stats["report_html"] = str(html_path)
    stats["report_csv"] = str(csv_path)
    return stats
