"""iPhone-App (Web-App für den Home-Bildschirm) und Siri-Schnittstelle.

  /app                   die App (Safari → Teilen → „Zum Home-Bildschirm")
  /app/login             Anmeldung mit JARVIS_ADMIN_TOKEN (bleibt 1 Jahr angemeldet)
  /api/...               Daten und Aktionen für die App
  /api/befehl            Befehl an Jarvis – auch für Siri-Kurzbefehle (Authorization: Bearer <Token>)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
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
def _cand_summary(row) -> dict:
    c = store.load(row)
    a = c.assessment
    return {"id": row["key"], "name": a.full_name, "tier": c.tier, "score": c.score,
            "kategorie": a.category,
            "bereich": (a.physician_specialty if a.category == "arzt" else a.nursing_field) or "",
            "deutsch": a.german_level, "anerkennung": a.recognition_status,
            "ort": a.current_location or "", "status": row["status"],
            "darf_anrufen": bool(row["consent_call"]), "whatsapp_link": c.whatsapp_link,
            "telefon": a.phone or ""}


@router.get("/api/uebersicht")
async def uebersicht(request: Request):
    authed(request)
    conn = store.connect()
    stats = store.stats_today(conn)
    stats["ziel"] = config.DAILY_TARGET
    rows = conn.execute(
        "SELECT * FROM candidates WHERE tier IN ('A','B') AND status IN ('neu','kontaktiert','interessiert') "
        "ORDER BY CASE status WHEN 'interessiert' THEN 0 ELSE 1 END, score DESC LIMIT 60").fetchall()
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
          "Darf ich Ihr Profil anonym passenden Kliniken vorstellen?",
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
    return out


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
