"""Autopilot: der tägliche Ablauf, ohne dass du etwas tun musst.

Morgens (JARVIS_MORNING_HOUR):
  1. Neue Bewerbungen (Ordner, E-Mail, Formular, WhatsApp) prüfen
  2. Web-Sourcing über alle Bereiche; reicht es nicht fürs Tagesziel → weitere Regionen
  3. Bei Bedarf neue Arbeitgeber mit offenen Stellen suchen
  4. Morgenbericht mit Top-Kandidaten an dich per WhatsApp
Stündlich Mo-Fr 9-18 Uhr:
  5. Kandidaten mit Einwilligung anrufen (KI-Telefonat) und Erstkontakt per WhatsApp-Vorlage
  6. Arbeitgeber anrufen und Kandidaten anbieten
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import companies, config, messaging, pipeline, store, voice
from .config import NURSING_FIELDS, PHYSICIAN_SPECIALTIES

log = logging.getLogger("jarvis.autopilot")

REGIONS = ["Zürich", "Bern", "Basel", "Luzern", "St. Gallen", "Aargau", "Graubünden", "Thurgau"]


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def morning(force: bool = False) -> dict:
    conn = store.connect()
    today = date.today().isoformat()
    if not force and store.get_state(conn, "morning") == today:
        return {"info": "heute schon gelaufen"}
    store.set_state(conn, "morning", today)
    messaging.notify_owner("☀️ Jarvis startet die Tagessuche …")

    result = pipeline.run(use_web=True)

    # Tagesziel noch nicht erreicht → zusätzliche Runden mit regionalem Fokus
    day_idx = date.today().toordinal()
    extra_rounds = 0
    while store.stats_today(conn)["vermittelbar_heute"] < config.DAILY_TARGET and extra_rounds < 3:
        region = REGIONS[(day_idx + extra_rounds) % len(REGIONS)]
        focuses = [f"Pflegefachperson {f} {region}" for f in NURSING_FIELDS[:3]]
        focuses += [f"Arzt {s} {region}" for s in PHYSICIAN_SPECIALTIES[day_idx % 4::4]]
        pipeline.run(use_folder=False, use_email=False, use_web=True, web_focuses=focuses)
        extra_rounds += 1

    # Genug Arbeitgeber in der Pipeline?
    new_companies = 0
    if len(store.list_companies(conn, "neu", 100)) < 15:
        for i in range(2):
            region = REGIONS[(day_idx + i) % len(REGIONS)]
            focus = "Pflegefachpersonen und Ärzte" if i == 0 else \
                f"Ärzte {', '.join(PHYSICIAN_SPECIALTIES[:4])}"
            try:
                new_companies += companies.find(focus, region)["neu"]
            except Exception as exc:  # noqa: BLE001
                log.error("Firmensuche fehlgeschlagen: %s", exc)

    stats = store.stats_today(conn)
    top = store.todays_shortlist(conn, 10)
    lines = [f"📋 *Jarvis Morgenbericht {date.today():%d.%m.}*",
             f"Vermittelbar heute: *{stats['vermittelbar_heute']}* / Ziel {config.DAILY_TARGET}",
             f"Offene A-Kandidaten gesamt: {stats['A_gesamt_offen']} · neue Firmen: {new_companies}", ""]
    for c in top:
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        lines.append(f"{c.tier} {c.score} · {a.full_name} · {role} · ID {store.candidate_key(c)}")
    lines.append(f"\nShortlist: {config.PUBLIC_URL}/shortlist?token={config.ADMIN_TOKEN}")
    if stats["vermittelbar_heute"] < config.DAILY_TARGET:
        lines.append("⚠️ Ziel noch nicht erreicht. Tipp: schreib mir 'Inserat für Facebook-Gruppen' – "
                     "Bewerber übers Formular sind sofort anrufbar.")
    messaging.notify_owner("\n".join(lines))
    result.update(stats)
    return result


def first_contacts(limit: int = 10) -> int:
    """Erstkontakt per WhatsApp-Vorlage an Kandidaten mit WhatsApp-Einwilligung."""
    conn = store.connect()
    rows = conn.execute(
        "SELECT * FROM candidates WHERE status='neu' AND tier IN ('A','B') AND consent_whatsapp=1 "
        "AND consent_call=0 AND phone IS NOT NULL ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    sent = 0
    for r in rows:
        if store.is_opted_out(conn, r["phone"]):
            continue
        c = store.load(r)
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        if messaging.send_first_contact_template(r["phone"], a.full_name.split()[0], role or ""):
            store.set_status(conn, r["key"], "kontaktiert", "WhatsApp-Vorlage (Autopilot)")
            sent += 1
    return sent


def call_round() -> dict:
    if not voice.within_call_hours():
        return {"info": "ausserhalb der Anrufzeiten"}
    conn = store.connect()
    out: dict = {"kandidaten": [], "firmen": [], "whatsapp": 0}
    if config.AUTO_CALL_CANDIDATES:
        for r in store.callable_candidates(conn, config.MAX_CALLS_PER_ROUND):
            out["kandidaten"].append(voice.place_call("kandidat", r["key"]))
    if config.AUTO_CALL_COMPANIES and store.todays_shortlist(conn, 1):
        for r in store.callable_companies(conn, max(1, config.MAX_CALLS_PER_ROUND // 2)):
            out["firmen"].append(voice.place_call("firma", str(r["id"])))
    try:
        out["whatsapp"] = first_contacts()
    except Exception as exc:  # noqa: BLE001
        log.error("WhatsApp-Erstkontakte fehlgeschlagen: %s", exc)
    return out


def tick() -> None:
    """Wird vom Server alle paar Minuten aufgerufen."""
    now = _now()
    conn = store.connect()
    if now.hour >= config.MORNING_HOUR and store.get_state(conn, "morning") != date.today().isoformat():
        try:
            morning()
        except Exception as exc:  # noqa: BLE001
            log.exception("Morgenlauf fehlgeschlagen")
            messaging.notify_owner(f"⚠️ Morgenlauf fehlgeschlagen: {exc}")
    slot = now.strftime("%Y-%m-%d %H")
    if voice.within_call_hours(now) and store.get_state(conn, "call_slot") != slot:
        store.set_state(conn, "call_slot", slot)
        try:
            log.info("Anrufrunde: %s", call_round())
        except Exception as exc:  # noqa: BLE001
            log.exception("Anrufrunde fehlgeschlagen")
            messaging.notify_owner(f"⚠️ Anrufrunde fehlgeschlagen: {exc}")
