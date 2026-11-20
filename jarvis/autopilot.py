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

from . import companies, config, matching, messaging, pipeline, store, voice
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

    # Offene Kundenaufträge zuerst suchen – dort ist das Geld schon sicher
    customer_focuses = [f"{k['needs']} {k['city'] or ''}".strip()
                        for k in store.customers(conn) if k["needs"]]
    result = pipeline.run(use_web=True, web_focuses=customer_focuses + pipeline.default_web_focuses())

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
                if config.LKW_ENABLED and i == 0:
                    new_companies += companies.find("LKW-Fahrer CE", "Deutschland", branche="lkw")["neu"]
            except Exception as exc:  # noqa: BLE001
                log.error("Firmensuche fehlgeschlagen: %s", exc)

    stats = store.stats_today(conn)
    if result.get("A") or result.get("B"):
        _maybe_call_owner(result.get("A", 0), result.get("B", 0))
    top = store.todays_shortlist(conn, 10)
    lines = [f"📋 *Jarvis Morgenbericht {date.today():%d.%m.}*",
             f"Vermittelbar heute: *{stats['vermittelbar_heute']}* / Ziel {config.DAILY_TARGET}",
             f"Offene A-Kandidaten gesamt: {stats['A_gesamt_offen']} · neue Firmen: {new_companies}", ""]
    for c in top:
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        lines.append(f"{c.tier} {c.score} · {a.full_name} · {role} · ID {store.candidate_key(c)[:6]}")
    delivered = matching.auto_deliver()
    if delivered:
        lines.append("\n📦 *Heute an Kunden geliefert*")
        lines += delivered
    open_needs = matching.open_customer_needs()
    if open_needs:
        lines.append("\n🎯 *Offene Kundenaufträge* (Jarvis sucht gezielt)")
        lines += open_needs[:8]
    sugg = matching.suggestions(conn)
    if sugg:
        lines.append("\n🤝 *Vermittlungsvorschläge*")
        lines += sugg
    due = store.followups_due(conn)
    if due:
        lines.append("\n🔁 *Nachfassen* (3+ Tage keine Antwort)")
        lines += [f"{r['name']} · {r['phone'] or '–'} · ID {r['key'][:6]}" for r in due[:8]]
    if not config.TWILIO_VOICE_FROM:
        # Ohne Telefonie-Anbieter: Anrufliste für dich (kostenlos über dein Handy)
        lines.append("\n📞 *Deine Anrufliste heute*")
        for c in top[:6]:
            lines.append(f"{c.assessment.full_name} · {c.assessment.phone} · ID {store.candidate_key(c)[:6]}")
    lines.append(f"\nApp: {config.PUBLIC_URL}/app")
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
    if not config.TWILIO_VOICE_FROM:
        try:
            return {"whatsapp": first_contacts(), "info": "keine Telefonie eingerichtet"}
        except Exception as exc:  # noqa: BLE001
            return {"fehler": str(exc)}
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


def _maybe_call_owner(a: int, b: int) -> None:
    try:
        text = (f"Hallo Cemal-Can, hier ist Jarvis. Ich habe gerade {a} sehr gute und {b} gute "
                f"Kandidaten gefunden.")
        log.info(voice.call_owner(text))
    except Exception as exc:  # noqa: BLE001
        log.error("Anruf an Owner fehlgeschlagen: %s", exc)


def day_round(now: datetime | None = None) -> dict:
    """Kleine Suchrunde tagsüber: 4 wechselnde Suchfokusse (Bereich × Region)."""
    now = now or _now()
    focuses = [f"Pflegefachperson {f}" for f in NURSING_FIELDS] + \
              [f"Arzt / Ärztin {s}" for s in PHYSICIAN_SPECIALTIES]
    n = now.toordinal() * 24 + now.hour
    picked = [f"{focuses[(n + i) % len(focuses)]} {REGIONS[(n + i) % len(REGIONS)]}" for i in range(4)]
    result = pipeline.run(use_folder=True, use_email=True, use_web=True, web_focuses=picked)
    result["fokus"] = picked
    if result.get("A") or result.get("B"):
        _maybe_call_owner(result.get("A", 0), result.get("B", 0))
        messaging.notify_owner(f"🔍 Suchrunde {now:%H:%M}: {result.get('A', 0)} A- und "
                               f"{result.get('B', 0)} B-Kandidaten neu gefunden. Details in der App.")
    return result


# Breite Berufsliste für das Tagesminimum – jede Runde andere Begriffe
MINIMUM_FOCUSES = [
    "Krankenschwester", "Gesundheits- und Krankenpflegerin", "examinierte Pflegefachkraft",
    "Altenpflegerin / Altenpfleger", "Intensivpflege Fachkraft", "OP-Pflege / OTA",
    "Anästhesiepflege", "Psychiatrische Pflege / Fachkrankenpfleger Psychiatrie", "Pflegefachfrau HF Schweiz",
    "Fachfrau Gesundheit FaGe", "Assistenzarzt / Assistenzärztin", "Facharzt Innere Medizin",
    "Facharzt Psychiatrie", "Facharzt Anästhesie", "Pflegefachkraft Geriatrie",
    "LKW: LKW-Fahrer CE", "LKW: Berufskraftfahrer", "LKW: Kraftfahrer Fernverkehr", "LKW: Fahrer ADR",
]


def ensure_minimum(now: datetime | None = None) -> dict:
    """Sucht in Runden, bis das Tagesminimum erreicht ist – höchstens bis MINIMUM_MAX_USD."""
    from . import budget
    now = now or _now()
    conn = store.connect()
    start_spend = budget.today_spend()
    rounds = 0
    while store.potentials_today(conn) < config.DAILY_MINIMUM:
        est = budget.EST_SEARCH_FOCUS_USD * 3
        if budget.today_spend() - start_spend + est > config.MINIMUM_MAX_USD or rounds >= 8:
            break
        k = (now.toordinal() * 7 + now.hour + rounds * 3)
        focuses = [MINIMUM_FOCUSES[(k + i) % len(MINIMUM_FOCUSES)] for i in range(3)]
        pipeline.run(use_folder=False, use_email=False, use_web=True, web_focuses=focuses)
        rounds += 1
    found = store.potentials_today(conn)
    return {"gefunden_heute": found, "ziel": config.DAILY_MINIMUM, "runden": rounds,
            "kosten": round(budget.today_spend() - start_spend, 2)}


def ads_due(now: datetime) -> list[int]:
    from . import ads
    return ads.due_slots(now)


def tick() -> None:
    """Wird vom Server alle paar Minuten aufgerufen."""
    now = _now()
    conn = store.connect()
    if now.hour >= 8 and store.get_state(conn, "drive") != date.today().isoformat():
        store.set_state(conn, "drive", date.today().isoformat())
        try:
            from . import deals
            log.info("Tagesantrieb: %s", deals.daily_drive())
        except Exception:  # noqa: BLE001
            log.exception("Tagesantrieb fehlgeschlagen")
    from . import budget
    morning_cost = budget.EST_SEARCH_FOCUS_USD * (len(NURSING_FIELDS) + len(PHYSICIAN_SPECIALTIES))
    if (now.hour >= config.MORNING_HOUR and store.get_state(conn, "morning") != date.today().isoformat()
            and not budget.auto_allowed(morning_cost)):
        store.set_state(conn, "morning", date.today().isoformat())
        budget.ask_once("heute nach Kandidaten suchen", morning_cost)
    if now.hour >= config.MORNING_HOUR and store.get_state(conn, "morning") != date.today().isoformat():
        try:
            morning()
        except Exception as exc:  # noqa: BLE001
            log.exception("Morgenlauf fehlgeschlagen")
            messaging.notify_owner(f"⚠️ Morgenlauf fehlgeschlagen: {exc}")
    if now.hour == 3 and store.get_state(conn, "update_day") != date.today().isoformat():
        store.set_state(conn, "update_day", date.today().isoformat())
        try:
            from . import updater
            log.info("Auto-Update: %s", updater.update())
        except Exception as exc:  # noqa: BLE001
            log.error("Auto-Update fehlgeschlagen: %s", exc)
    for slot_i in ads_due(now):
        key = f"ads:{date.today()}:{slot_i}"
        if store.get_state(conn, key):
            continue
        store.set_state(conn, key, "1")
        if not budget.auto_allowed(budget.EST_AD_USD * 2):
            budget.ask_once("ein Inserat schreiben", budget.EST_AD_USD * 2)
            continue
        try:
            from . import ads
            log.info("Inserat: %s", ads.daily_round(slot_i))
        except Exception:  # noqa: BLE001
            log.exception("Inserat fehlgeschlagen")
    if config.DAILY_MINIMUM > 0 and now.hour in (9, 13, 17):
        key = f"minimum:{date.today()}:{now.hour}"
        if not store.get_state(conn, key):
            store.set_state(conn, key, "1")
            if store.potentials_today(conn) < config.DAILY_MINIMUM:
                try:
                    r = ensure_minimum(now)
                    log.info("Tagesminimum: %s", r)
                    if r["gefunden_heute"] >= r["ziel"]:
                        messaging.notify_owner(f"✅ Tagesziel erreicht: {r['gefunden_heute']} neue potenzielle "
                                               f"Kandidaten heute (Kosten {r['kosten']:.2f} $). Details in der App.")
                    elif now.hour == 17:
                        messaging.notify_owner(
                            f"⚠️ Heute erst {r['gefunden_heute']} von {r['ziel']} neuen Kandidaten – ich habe bis zur "
                            f"Kostengrenze ({config.MINIMUM_MAX_USD:.2f} $) gesucht. Morgen suche ich weiter. "
                            f"Tipp: Inserat posten bringt zusätzliche Bewerber.")
                except Exception:  # noqa: BLE001
                    log.exception("Tagesminimum fehlgeschlagen")
    every = config.SEARCH_EVERY_HOURS
    if (every > 0 and config.SEARCH_HOURS[0] <= now.hour < config.SEARCH_HOURS[1]
            and store.get_state(conn, "morning") == date.today().isoformat()):
        last = store.get_state(conn, "day_round")
        due = not last or (now - datetime.fromisoformat(last)).total_seconds() >= every * 3600 - 300
        if due and not budget.auto_allowed(budget.EST_SEARCH_FOCUS_USD * 4):
            due = False
        if due:
            store.set_state(conn, "day_round", now.isoformat(timespec="minutes"))
            try:
                log.info("Suchrunde: %s", day_round(now))
            except Exception:  # noqa: BLE001
                log.exception("Suchrunde fehlgeschlagen")
    slot = now.strftime("%Y-%m-%d %H")
    if voice.within_call_hours(now) and store.get_state(conn, "call_slot") != slot:
        store.set_state(conn, "call_slot", slot)
        try:
            log.info("Anrufrunde: %s", call_round())
        except Exception as exc:  # noqa: BLE001
            log.exception("Anrufrunde fehlgeschlagen")
            messaging.notify_owner(f"⚠️ Anrufrunde fehlgeschlagen: {exc}")
