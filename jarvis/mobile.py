"""iPhone-App (Web-App für den Home-Bildschirm) und Siri-Schnittstelle.

  /app                   die App (Safari → Teilen → „Zum Home-Bildschirm")
  /app/login             Anmeldung mit JARVIS_ADMIN_TOKEN (bleibt 1 Jahr angemeldet)
  /api/...               Daten und Aktionen für die App
  /api/befehl            Befehl an Jarvis – auch für Siri-Kurzbefehle (Authorization: Bearer <Token>)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import agent, config, matching, messaging, pricing, store, voice

router = APIRouter()
STATIC = Path(__file__).parent / "static"
COOKIE = "jarvis_session"
SIRI_WAIT_S = 25  # Siri wartet nicht ewig; längere Aufträge melden sich per WhatsApp


# --------------------------------------------------------------------------- Anmeldung
def _session_value() -> str:
    return hashlib.sha256(("jarvis-app:" + config.ADMIN_TOKEN).encode()).hexdigest()


def authed(request: Request) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(503, "JARVIS_ADMIN_TOKEN ist nicht gesetzt")
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), config.ADMIN_TOKEN):
        return
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), _session_value()):
        return
    raise HTTPException(401, "Nicht angemeldet")


_login_attempts: dict[str, list[float]] = {}


@router.get("/app/login", response_class=HTMLResponse)
async def login_page(fehler: int = 0):
    return HTMLResponse(LOGIN_HTML.replace("{{FEHLER}}", "Falscher Code." if fehler else ""))


@router.post("/app/login")
async def login(request: Request, token: str = Form(...)):
    ip = request.client.host if request.client else "?"
    now = time.time()
    tries = [t for t in _login_attempts.get(ip, []) if t > now - 900]
    if len(tries) >= 10:
        raise HTTPException(429, "Zu viele Versuche, bitte 15 Minuten warten")
    _login_attempts[ip] = tries + [now]
    if not config.ADMIN_TOKEN or not hmac.compare_digest(token.strip(), config.ADMIN_TOKEN):
        return RedirectResponse("/app/login?fehler=1", status_code=303)
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE, _session_value(), max_age=365 * 24 * 3600, httponly=True,
                    secure=config.PUBLIC_URL.startswith("https"), samesite="lax")
    return resp


@router.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    try:
        authed(request)
    except HTTPException:
        return RedirectResponse("/app/login", status_code=303)
    return FileResponse(STATIC / "app.html", media_type="text/html")


@router.get("/api/team")
async def team_status(request: Request):
    authed(request)
    from . import team
    return {"team": await asyncio.to_thread(team.status)}


@router.get("/api/stellen")
async def stellen(request: Request):
    authed(request)
    conn = store.connect()
    out = []
    for j in store.jobs(conn, only_active=False):
        m = store.job_matches(conn, j, 8)
        out.append({**j, "link": f"{config.PUBLIC_URL}/jobs/{j['id']}",
                    "passend": [{"id": r["key"], "name": _display_name(store.load(r).assessment),
                                 "details": _details(store.load(r).assessment), "tier": r["tier"],
                                 "status": r["status"]} for r in m]})
    return {"stellen": out, "seite": f"{config.PUBLIC_URL}/jobs"}


@router.post("/api/stellen")
async def stelle_neu(request: Request, daten: dict = Body(...)):
    authed(request)
    title = (daten.get("titel") or "").strip()
    if not title:
        raise HTTPException(400, "Titel fehlt")
    bereich = daten.get("bereich") if daten.get("bereich") in ("lkw", "pflege", "arzt") else "lkw"
    jid = store.add_job(store.connect(), title, bereich, daten.get("ort", ""), daten.get("beschreibung", ""),
                        daten.get("gehalt", ""))
    return {"meldung": f"✅ Stelle #{jid} ist online: {config.PUBLIC_URL}/jobs/{jid}", "id": jid}


@router.post("/api/stellen/auto")
async def stellen_auto(request: Request):
    authed(request)
    from . import jobboard
    r = await asyncio.to_thread(jobboard.sync)
    return {"meldung": f"📌 Stellen aus gefundenen Arbeitgebern: {r['neu']} neu, {r['aktualisiert']} aktualisiert, "
                       f"{r['offline']} offline (kein aktueller Bedarf mehr)."}


@router.post("/api/stellen/{jid}/aktiv")
async def stelle_aktiv(request: Request, jid: int, daten: dict = Body(...)):
    authed(request)
    store.set_job_active(store.connect(), jid, bool(daten.get("aktiv")))
    return {"meldung": "Gespeichert"}


@router.post("/api/tiefensuche")
async def tiefensuche(request: Request, daten: dict = Body(...)):
    """{"bereich": "lkw"|"pflege", "bestaetigt": false} → erst Kosten nennen, mit bestaetigt=true starten."""
    authed(request)
    from . import autopilot
    bereich = "lkw" if daten.get("bereich") == "lkw" else "pflege"
    cost = autopilot.deep_cost(bereich)
    if not daten.get("bestaetigt"):
        return {"kosten": cost, "suchen": len(autopilot.deep_focuses(bereich))}
    threading.Thread(target=autopilot.deep_search, args=(bereich,), daemon=True).start()
    return {"meldung": f"🔎 Tiefensuche läuft (ca. {cost:.2f} $, 5–10 Minuten). Du bekommst eine Mitteilung."}


@router.get("/app/zentrale", response_class=HTMLResponse)
async def zentrale_page(request: Request):
    """Großer Bildschirm (Notebook/Monitor): Jarvis-Kommandozentrale."""
    try:
        authed(request)
    except HTTPException:
        return RedirectResponse("/app/login", status_code=303)
    return FileResponse(STATIC / "zentrale.html", media_type="text/html")


@router.get("/api/zentrale")
async def zentrale_daten(request: Request):
    authed(request)
    from datetime import timedelta
    from . import budget
    conn = store.connect()
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    found = dict(conn.execute("SELECT found_on, COUNT(*) FROM candidates WHERE found_on >= ? AND tier != 'X' "
                              "GROUP BY found_on", (days[0],)).fetchall())
    serie = [{"tag": d, "neu": found.get(d, 0),
              "kosten": round(float(store.get_state(conn, f"spend:{d}") or 0), 2)} for d in days]
    cnt = lambda q, *a: conn.execute(q, a).fetchone()[0]  # noqa: E731
    bereiche = {k: cnt("SELECT COUNT(*) FROM candidates WHERE category=? AND tier != 'X'", k)
                for k in ("lkw", "pflege", "arzt")}
    pipeline = {s: cnt("SELECT COUNT(*) FROM candidates WHERE status=? AND tier != 'X'", s)
                for s in ("neu", "kontaktiert", "interessiert", "vorgestellt", "gespraech", "vermittelt")}
    return {"serie": serie, "bereiche": bereiche, "pipeline": pipeline,
            "direkt": cnt("SELECT COUNT(*) FROM candidates WHERE status='neu' AND tier != 'X' AND phone IS NOT NULL AND phone != ''"),
            "firmen": cnt("SELECT COUNT(*) FROM companies"),
            "kosten_heute": round(budget.today_spend(), 2), "budget": config.DAILY_BUDGET_USD,
            "freigegeben": budget.autonomy_active(), "umsatz": store.revenue_month(conn),
            "ziel": config.REVENUE_GOAL, "meldungen": store.notifications(conn, 12)}


@router.get("/app/manifest.webmanifest")
async def manifest():
    return JSONResponse({
        "name": "Jarvis", "short_name": "Jarvis", "start_url": "/app", "scope": "/",
        "display": "standalone", "background_color": "#0b6e4f", "theme_color": "#0b6e4f",
        "lang": "de",
        "icons": [{"src": "/app/icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "/app/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, media_type="application/manifest+json")


@router.get("/app/icon-{size}.png")
async def icon(size: int):
    if size not in (180, 512):
        raise HTTPException(404)
    return FileResponse(STATIC / f"icon-{size}.png", media_type="image/png")


# --------------------------------------------------------------------------- Daten
def _display_name(a) -> str:
    from .whatsapp import role_phrase
    name = (a.full_name or "").strip()
    if not name or name.lower() in ("unbekannt", "unknown", "n/a", "-"):
        return f"{role_phrase(a)}{' · ' + a.current_location if a.current_location else ''}"
    return name


def _details(a) -> str:
    yn = lambda v, t: (t + " ✓") if v else None  # noqa: E731
    if a.category == "lkw":
        parts = [f"Führerschein {a.driving_license}" if a.driving_license else "Führerschein ?",
                 yn(a.code95, "Modul 95"), yn(a.driver_card, "Fahrerkarte"), yn(a.adr, "ADR"), a.traffic_type]
    else:
        rec = {"anerkannt": "SRK/MEBEKO ✓", "positiver_precheck": "Pre-Check ✓", "laufend": "Anerkennung läuft",
               "nicht_noetig": "CH-Diplom", "fehlt": "Anerkennung fehlt"}.get(a.recognition_status)
        parts = [a.physician_specialty if a.category == "arzt" else a.nursing_field,
                 f"Deutsch {a.german_level}" if a.german_level != "unbekannt" else None, rec]
    parts.append(a.current_location)
    return " · ".join(p for p in parts if p)


def _cand_summary(row) -> dict:
    c = store.load(row)
    a = c.assessment
    if a.phone and c.whatsapp_message:  # Link immer mit richtiger Ländervorwahl neu bauen
        from .whatsapp import build_link
        de = a.category == "lkw" or "deutschland" in (a.current_location or "").lower()
        c.whatsapp_link = build_link(a.phone, c.whatsapp_message, "49" if de else "41") or c.whatsapp_link
    return {"id": row["key"], "name": _display_name(a), "details": _details(a), "tier": c.tier, "score": c.score,
            "kategorie": a.category,
            "bereich": (a.physician_specialty if a.category == "arzt" else a.nursing_field) or "",
            "deutsch": a.german_level, "anerkennung": a.recognition_status,
            "ort": a.current_location or "", "status": row["status"],
            "darf_anrufen": bool(row["consent_call"]), "whatsapp_link": c.whatsapp_link,
            "telefon": a.phone or "",
            "quelle": person_link(c),
            "nachricht": _portal_text(c)}


def person_link(c) -> str:
    """Direkt zur Person: echte Einzelanzeige, sonst eine Kleinanzeigen-Suche nach Beruf + Ort dieser Person
    (statt der langen Übersichtsliste)."""
    import re as _re
    src = c.source or ""
    if not src.startswith("http"):
        return ""
    if "kleinanzeigen.de" not in src or "/s-anzeige/" in src:
        return src
    a = c.assessment
    loc = _re.sub(r"\d{4,5}", " ", a.current_location or "")
    loc = _re.sub(r"\(.*?\)|deutschland|nordrhein-westfalen|niedersachsen|bayern|baden-württemberg|hessen|"
                  r"sachsen|thüringen|rheinland-pfalz|brandenburg|schleswig-holstein|mecklenburg-vorpommern|"
                  r"sachsen-anhalt|saarland|nrw", " ", loc, flags=_re.I)
    city = next((w for w in _re.split(r"[,\s/]+", loc) if len(w) > 2), "")
    what = "lkw fahrer sucht" if a.category == "lkw" else ("arzt sucht" if a.category == "arzt" else "pflege sucht")
    words = [w.lower() for w in (what + " " + city).split() if w]
    slug = "-".join(_re.sub(r"[^a-z0-9äöüß-]", "", w) for w in words)
    return f"https://www.kleinanzeigen.de/s-jobs/{slug}/k0c102"


def _portal_text(c) -> str:
    from . import outreach
    try:
        return outreach.portal_message(c)
    except Exception:  # noqa: BLE001
        return ""


@router.post("/api/autonomie/weiter")
async def autonomie_weiter(request: Request):
    authed(request)
    from . import budget
    return {"info": budget.autonomy_continue()}


@router.get("/api/gespraeche")
async def gespraeche(request: Request):
    """Die letzten KI-Gespräche zum Mitlesen."""
    authed(request)
    out = []
    for c in store.recent_convos(store.connect(), 30):
        msgs = [m for m in c["messages"] if isinstance(m.get("content"), str)]
        out.append({"id": c["id"], "art": c["kind"], "aktualisiert": c["updated"],
                    "verlauf": [{"von": "jarvis" if m["role"] == "assistant" else "person",
                                 "text": m["content"][:1500]} for m in msgs[-12:]]})
    return {"gespraeche": out}


@router.get("/api/uebersicht")
async def uebersicht(request: Request):
    authed(request)
    conn = store.connect()
    stats = store.stats_today(conn)
    stats["ziel"] = config.DAILY_TARGET
    from . import budget
    stats["kosten_heute"] = round(budget.today_spend(), 2)
    stats["budget"] = config.DAILY_BUDGET_USD
    stats["potenzielle_heute"] = store.potentials_today(conn)
    stats["umsatz"] = store.revenue_month(conn)
    stats["umsatz_ziel"] = config.REVENUE_GOAL
    stats["minimum"] = config.DAILY_MINIMUM
    from . import inbox
    until = budget.autonomy_until()
    stats["autonomie"] = {"aktiv": budget.autonomy_active(), "taeglich": config.ASK_DAILY,
                          "budget": config.DAILY_BUDGET_USD, "bis": f"{until:%d.%m.%Y}", "tage": config.AUTO_DAYS,
                          "bald": (until - date.today()).days <= 1, "chat_heute": budget.chat_spend_today(),
                          "chat_max": config.CHAT_MAX_USD, "postfach": inbox.status_text(),
                          "gespraeche": conn.execute("SELECT COUNT(*) FROM convos").fetchone()[0]}
    rows = conn.execute(
        "SELECT * FROM candidates WHERE tier IN ('A','B','C') AND status IN ('neu','kontaktiert','interessiert') "
        "ORDER BY CASE status WHEN 'interessiert' THEN 0 ELSE 1 END, tier, score DESC LIMIT 100").fetchall()
    calls = conn.execute("SELECT * FROM calls ORDER BY id DESC LIMIT 15").fetchall()
    call_list = []
    for c in calls:
        label = c["target_key"] or c["phone"]
        if c["target_type"] == "kandidat":
            r = store.get_candidate(conn, c["target_key"])
            label = r["name"] if r else label
        elif c["target_type"] == "firma":
            r = store.get_company(conn, int(c["target_key"]))
            label = r["name"] if r else label
        else:  # eingehender Anruf
            try:
                info = json.loads(c["summary"] or "{}")
                label = "☎️ " + (info.get("firma") or info.get("name") or c["phone"])
            except json.JSONDecodeError:
                label = "☎️ " + c["phone"]
        summary = ""
        if c["summary"]:
            try:
                summary = json.loads(c["summary"]).get("summary", "")
            except json.JSONDecodeError:
                summary = c["summary"]
        call_list.append({"typ": c["target_type"], "name": label, "status": c["status"],
                          "zeit": c["started"], "zusammenfassung": summary})
    return {"stats": stats, "kandidaten": [_cand_summary(r) for r in rows],
            "firmen": [dict(r) for r in conn.execute(
                "SELECT * FROM companies ORDER BY status='kunde' DESC, status='interessiert' DESC, id DESC LIMIT 80")],
            "preise": pricing.overview(),
            "meldungen": store.notifications(conn, 15),
            "anrufe": call_list, "anrufzeit": voice.within_call_hours()}


def leitfaden(row) -> list[str]:
    """Gesprächsleitfaden für deinen eigenen Anruf (kostenlos über dein Handy)."""
    a = store.load(row).assessment
    rec = "MEBEKO" if a.category == "arzt" else "SRK"
    first = a.full_name.split()[0] if a.full_name else ""
    q = [f"Grüezi {first}, hier ist {config.RECRUITER_NAME} von {config.AGENCY_NAME}. Passt es kurz?",
         "Was ist Ihnen bei der nächsten Stelle am wichtigsten (Region, Pensum, Team, Lohn)?"]
    if a.has_diploma_certificate is not True:
        q.append("Haben Sie Ihr Diplom bzw. Ihre Berufsurkunde als Dokument vorliegen?")
    if a.german_level in ("unbekannt", "A1", "A2", "B1"):
        q.append("Welches Deutsch-Zertifikat haben Sie (mindestens B2 nötig)?")
    if a.recognition_status in ("unbekannt", "fehlt", "laufend"):
        q.append(f"Wie ist der Stand bei der {rec}-Anerkennung? Haben Sie schon einen Pre-Check?")
    if not a.availability:
        q.append("Ab wann könnten Sie starten?")
    q += ["Welche Regionen in der Schweiz kommen in Frage?",
          "Darf ich Ihr Profil an unsere Schweizer Partner-Personalvermittlung weitergeben?",
          "Abschluss: nächsten Schritt + Termin festhalten, Lebenslauf per WhatsApp anfordern."]
    return q


@router.get("/api/kandidat/{key}")
async def kandidat(request: Request, key: str):
    authed(request)
    out = agent.t_kandidat(key)
    if "fehler" in out:
        raise HTTPException(404, "Kandidat nicht gefunden")
    conn = store.connect()
    row = store.get_candidate(conn, key)
    out["passende_firmen"] = matching.matches(conn, row)
    out["leitfaden"] = leitfaden(row)
    from . import outreach
    c = store.load(row)
    out["anzeige_name"] = _display_name(c.assessment)
    out["quelle"] = person_link(c)
    out["nachricht"] = outreach.portal_message(c)
    out["whatsapp_kontakt"] = outreach.wa_link()
    from urllib.parse import quote as _q
    from . import pricing
    a = c.assessment
    price = pricing.for_candidate(a.category, a.nursing_field, a.adr) or "nur bei Einstellung"
    profil = (f"Kandidatenvorschlag von {config.AGENCY_NAME}:\n\n{matching.anonymous_profile(row)}\n\n"
              f"Konditionen: {price}. Bei Interesse schicke ich sofort Lebenslauf und Unterlagen.\n"
              f"{config.RECRUITER_NAME}")
    out["profil_text"] = profil
    out["profil_whatsapp"] = "https://wa.me/?text=" + _q(profil)
    cvp = store.get_state(conn, f"cv:{row['key']}")
    out["lebenslauf"] = bool(cvp and Path(cvp).exists())
    from . import deals
    out["dokumente"] = store.doc_status(conn, row["key"], c.assessment.category)
    out["dokumente_text"] = deals.doc_request_text(row)
    out["dokumente_whatsapp"] = deals.whatsapp_to_candidate(row, out["dokumente_text"])
    return out


@router.get("/api/kandidat/{key}/lebenslauf")
async def lebenslauf(request: Request, key: str):
    authed(request)
    conn = store.connect()
    row = store.get_candidate(conn, key)
    path = store.get_state(conn, f"cv:{row['key']}") if row else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "Kein Lebenslauf vorhanden")
    return FileResponse(path, filename=Path(path).name.split("-", 2)[-1])


@router.post("/api/kandidat/{key}/firmen_suchen")
async def firmen_fuer_kandidat(request: Request, key: str):
    """Sucht im Web Firmen mit offenen Stellen in der Nähe des Kandidaten (ca. 3–5 Cent)."""
    authed(request)
    conn = store.connect()
    row = store.get_candidate(conn, key)
    if not row:
        raise HTTPException(404, "Kandidat nicht gefunden")
    from . import companies
    from .whatsapp import role_phrase
    a = store.load(row).assessment
    lkw = a.category == "lkw"
    region = a.current_location or ("Deutschland" if lkw else "Deutschschweiz")
    await asyncio.to_thread(companies.find, role_phrase(a), region, None, "lkw" if lkw else "")
    found = matching.matches(conn, store.get_candidate(conn, key))
    return {"meldung": f"{len(found)} passende Firmen gefunden", "firmen": found}


@router.post("/api/kandidat/{key}/schritt")
async def kandidat_schritt(request: Request, key: str, daten: dict = Body(...)):
    """Vermittlungs-Schritte: gespraech | eingestellt | unterlagen_senden"""
    authed(request)
    from . import deals
    art = daten.get("art")
    firma = int(daten["firma_id"]) if daten.get("firma_id") else None
    try:
        if art == "gespraech":
            msg = deals.mark_interview(key, daten.get("wann", ""), firma)
        elif art == "eingestellt":
            msg = deals.mark_hired(key, firma, daten.get("start") or date.today().isoformat(), daten.get("honorar"))
        elif art == "unterlagen_senden" and firma:
            msg = await asyncio.to_thread(deals.send_documents, key, firma)
        else:
            raise HTTPException(400, "Unbekannter Schritt")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    return {"meldung": msg}


@router.get("/api/vertrieb")
async def vertrieb(request: Request):
    authed(request)
    from . import deals
    conn = store.connect()
    verm = store.placements(conn)
    for v in verm:
        firm = store.get_company(conn, v["company_id"]) if v["company_id"] else None
        v["firma"] = firm["name"] if firm else ""
        v["firma_adresse"] = (firm["address"] if firm else "") or ""
        v["rechnung_nr"] = store.get_state(conn, f"invoice_no:{v['id']}") or ""
    return {"plan": deals.sales_plan(), "umsatz": store.revenue_month(conn), "ziel": config.REVENUE_GOAL,
            "vermittlungen": verm}


@router.get("/api/bewerbungen")
async def bewerbungen(request: Request):
    authed(request)
    from . import deals
    return {"liste": deals.application_queue(), "automatisch": config.AUTO_APPLY}


@router.post("/api/bewerbungen/senden")
async def bewerbungen_senden(request: Request):
    authed(request)
    from . import deals
    res = await asyncio.to_thread(deals.send_applications)
    return {"meldung": f"{len([r for r in res if r.startswith('✅')])} Bewerbungen gesendet", "details": res}


@router.post("/api/vertrieb/{cid}")
async def vertrieb_ergebnis(request: Request, cid: int, daten: dict = Body(...)):
    authed(request)
    from . import deals
    msg = await asyncio.to_thread(deals.record_call, cid, daten.get("ergebnis", ""), daten.get("email", ""),
                                  daten.get("kontakt", ""), daten.get("notiz", ""))
    return {"meldung": msg}


@router.post("/api/vermittlung/{pid}/rechnung")
async def vermittlung_rechnung(request: Request, pid: int, daten: dict = Body(default={})):
    authed(request)
    from . import invoices
    conn = store.connect()
    p = next((x for x in store.placements(conn) if x["id"] == pid), None)
    if not p:
        raise HTTPException(404, "Vermittlung nicht gefunden")
    if daten.get("adresse") and p["company_id"]:
        store.set_company_address(conn, p["company_id"], daten["adresse"])
    try:
        msg = await asyncio.to_thread(invoices.send_invoice, pid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    return {"meldung": msg}


@router.get("/api/vermittlung/{pid}/rechnung.pdf")
async def vermittlung_pdf(request: Request, pid: int):
    authed(request)
    from . import invoices
    p = next((x for x in store.placements(store.connect()) if x["id"] == pid), None)
    if not p:
        raise HTTPException(404, "Vermittlung nicht gefunden")
    fehlt = invoices.missing_business_data()
    if fehlt:
        raise HTTPException(400, "Unter ⚙️ fehlt noch: " + ", ".join(fehlt))
    if not await asyncio.to_thread(invoices.ensure_reportlab):
        raise HTTPException(503, "PDF-Baustein fehlt – bitte 'Jarvis aktualisieren' drücken.")
    path, number, _ = await asyncio.to_thread(invoices.build_pdf, p)
    return FileResponse(path, media_type="application/pdf", filename=f"{number}.pdf")


@router.post("/api/vermittlung/{pid}/bezahlt")
async def vermittlung_bezahlt(request: Request, pid: int):
    authed(request)
    store.set_placement_status(store.connect(), pid, "bezahlt")
    return {"meldung": "Als bezahlt markiert 💶"}


@router.post("/api/kandidat/{key}/loeschen")
async def kandidat_loeschen(request: Request, key: str):
    authed(request)
    if not store.delete_candidate(store.connect(), key):
        raise HTTPException(404, "Kandidat nicht gefunden")
    return {"meldung": "Gelöscht 🗑"}


@router.post("/api/kandidat/{key}/vorstellen")
async def kandidat_vorstellen(request: Request, key: str, daten: dict = Body(...)):
    authed(request)
    return {"meldung": matching.present(key, int(daten.get("firma_id", 0)))}


@router.post("/api/kandidat/{key}/anrufen")
async def kandidat_anrufen(request: Request, key: str):
    authed(request)
    return {"meldung": voice.place_call("kandidat", key)}


@router.post("/api/kandidat/{key}/status")
async def kandidat_status(request: Request, key: str, daten: dict = Body(...)):
    authed(request)
    try:
        store.set_status(store.connect(), key, daten.get("status", ""), daten.get("notiz", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"meldung": "Gespeichert"}


@router.post("/api/firma/{cid}/anrufen")
async def firma_anrufen(request: Request, cid: int):
    authed(request)
    return {"meldung": voice.place_call("firma", str(cid))}


@router.post("/api/firma/{cid}/status")
async def firma_status(request: Request, cid: int, daten: dict = Body(...)):
    authed(request)
    try:
        store.set_company_status(store.connect(), cid, daten.get("status", ""), daten.get("notiz", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"meldung": "Gespeichert"}


# --------------------------------------------------------------------------- Befehle (App + Siri)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(job_id: str, text: str) -> None:
    try:
        reply = agent.handle_owner(text)
    except Exception as exc:  # noqa: BLE001
        reply = f"Fehler: {exc}"
    with _jobs_lock:
        job = _jobs[job_id]
        job.update(status="fertig", antwort=reply)
        notify = job.get("per_whatsapp")
    if notify:
        messaging.notify_owner(f"🤖 Zu deinem Auftrag „{text[:60]}“:\n\n{reply}")


@router.post("/api/befehl")
async def befehl(request: Request, daten: dict = Body(...)):
    """{"text": "...", "warten": 25}  → wartet bis zu N Sekunden auf die Antwort (für Siri)."""
    authed(request)
    text = (daten.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Kein Text")
    wait = min(float(daten.get("warten", 0) or 0), 55)
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        # alte Aufträge aufräumen
        for k in [k for k, v in _jobs.items() if v["start"] < time.time() - 3600]:
            _jobs.pop(k)
        _jobs[job_id] = {"status": "läuft", "antwort": "", "start": time.time(), "text": text}
    threading.Thread(target=_run_job, args=(job_id, text), daemon=True).start()

    deadline = time.time() + wait
    while time.time() < deadline:
        with _jobs_lock:
            if _jobs[job_id]["status"] == "fertig":
                return {"job": job_id, "status": "fertig", "antwort": _jobs[job_id]["antwort"]}
        await _sleep(0.5)
    if wait:
        with _jobs_lock:
            _jobs[job_id]["per_whatsapp"] = True
        return {"job": job_id, "status": "läuft",
                "antwort": "Ich arbeite daran. Das Ergebnis schicke ich dir per WhatsApp."}
    return {"job": job_id, "status": "läuft"}


@router.get("/api/befehl/{job_id}")
async def befehl_status(request: Request, job_id: str):
    authed(request)
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unbekannter Auftrag")
    return {"job": job_id, "status": job["status"], "antwort": job["antwort"]}


@router.get("/api/einstellungen")
async def einstellungen(request: Request):
    authed(request)
    return store.settings_overview()


@router.post("/api/einstellungen")
async def einstellungen_setzen(request: Request, daten: dict = Body(...)):
    authed(request)
    conn = store.connect()
    try:
        for k, v in daten.items():
            store.save_setting(conn, k, str(v))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"meldung": "Gespeichert ✅"}


@router.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@router.get("/api/push/key")
async def push_key(request: Request):
    authed(request)
    from . import push
    return {"key": push.vapid_public_b64()}


@router.post("/api/push/abo")
async def push_abo(request: Request, daten: dict = Body(...)):
    authed(request)
    from . import push
    try:
        push.subscribe(daten)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    n = await asyncio.to_thread(push.send, "Jarvis 🔔", "Mitteilungen sind aktiviert. Ich melde mich, sobald ich gute Kandidaten finde.")
    return {"meldung": "Mitteilungen aktiviert ✅" if n else "Gespeichert – Testmitteilung kam nicht an."}


@router.post("/api/testmail")
async def testmail(request: Request):
    authed(request)
    from .matching import send_email
    to = config.OWNER_EMAIL or config.SMTP_USER
    try:
        await asyncio.to_thread(send_email, to, "Jarvis Testmail ✅",
                                "Hallo Cemal-Can,\n\ndas Senden von E-Mails funktioniert.\n\nJarvis")
    except Exception as exc:  # noqa: BLE001
        from . import inbox
        postfach = await asyncio.to_thread(inbox.check)
        raise HTTPException(502, f"Senden: ❌ {exc}\n\nPosteingang: {postfach}") from exc
    from . import inbox
    postfach = await asyncio.to_thread(inbox.check)
    return {"meldung": f"Testmail an {to} gesendet ✅\nPosteingang: {postfach}"}


@router.post("/api/microsoft/start")
async def microsoft_start(request: Request):
    authed(request)
    from . import msauth
    try:
        return await asyncio.to_thread(msauth.start)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/facebook/test")
async def facebook_test(request: Request):
    authed(request)
    from . import ads
    return {"meldung": await asyncio.to_thread(ads.check_facebook)}


@router.post("/api/testanruf")
async def testanruf(request: Request):
    authed(request)
    try:
        msg = await asyncio.to_thread(agent.t_mich_anrufen)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Anruf fehlgeschlagen: {exc}") from exc
    return {"meldung": msg}


@router.post("/api/update")
async def update_now(request: Request):
    """Neueste Jarvis-Version von GitHub holen und neu starten."""
    authed(request)
    from . import updater
    try:
        return await asyncio.to_thread(updater.update, True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Update fehlgeschlagen: {exc}") from exc


@router.get("/api/verlauf")
async def verlauf(request: Request):
    """Bisheriger Chat mit Jarvis (WhatsApp und App teilen sich den Verlauf)."""
    authed(request)
    messages, _ = store.load_chat(store.connect(), config.OWNER_WHATSAPP or "app")
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            text = content.split("] ", 1)[-1] if content.startswith("[") else content
            out.append({"von": "du" if m["role"] == "user" else "jarvis", "text": text})
            continue
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts and m["role"] == "assistant":
            out.append({"von": "jarvis", "text": "".join(texts)})
    return out[-40:]


async def _sleep(s: float) -> None:
    import asyncio
    await asyncio.sleep(s)


LOGIN_HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Jarvis">
<link rel="apple-touch-icon" href="/app/icon-180.png"><link rel="manifest" href="/app/manifest.webmanifest">
<title>Jarvis</title><style>
:root{--bg:#f2f4f7;--card:#fff;--text:#111;--muted:#667;--accent:#0b6e4f}
@media (prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--text:#f2f2f7;--muted:#98989f;--accent:#30d18f}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);
font:17px -apple-system,system-ui,sans-serif;padding:16px;box-sizing:border-box}
form{background:var(--card);padding:28px 22px;border-radius:18px;width:100%;max-width:360px;text-align:center}
img{width:72px;height:72px;border-radius:16px}h1{margin:12px 0 4px}p{color:var(--muted);margin:0 0 18px}
input{width:100%;box-sizing:border-box;padding:14px;border-radius:12px;border:1px solid #8884;background:var(--bg);
color:var(--text);font-size:17px}button{margin-top:12px;width:100%;padding:14px;border:0;border-radius:12px;
background:var(--accent);color:#fff;font-size:17px;font-weight:600}.f{color:#e5484d;min-height:22px;margin-top:8px}
</style></head><body><form method="post" action="/app/login">
<img src="/app/icon-180.png" alt=""><h1>Jarvis</h1><p>Hansa Personal · Zugangscode eingeben</p>
<input name="token" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Anmelden</button><div class="f">{{FEHLER}}</div></form></body></html>"""
