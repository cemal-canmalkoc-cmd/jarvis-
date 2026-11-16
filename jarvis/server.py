"""Jarvis-Server (FastAPI).

  /bewerbung        Bewerbungsformular für Kandidaten (mit Einwilligungen)
  /whatsapp         Twilio-Webhook: deine Befehle + Kandidaten-Chats
  /voice/twiml      Twilio: Anruf verbunden → Gespräch starten
  /voice/relay      WebSocket: Live-Gespräch (ConversationRelay)
  /voice/status     Twilio: Anrufstatus
  /shortlist        Tages-Shortlist (mit ?token=JARVIS_ADMIN_TOKEN)

Start:  uvicorn jarvis.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.websockets import WebSocketDisconnect

from . import agent, autopilot, config, messaging, mobile, pipeline, report, sources, store, voice
from .config import NURSING_FIELDS, PHYSICIAN_SPECIALTIES

log = logging.getLogger("jarvis.server")
UPLOAD_DIR = config.DATA_DIR / "uploads"
MAX_UPLOAD = 10 * 1024 * 1024
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


# --------------------------------------------------------------------------- Autopilot-Takt
async def _autopilot_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(autopilot.tick)
        except Exception:  # noqa: BLE001
            log.exception("Autopilot-Tick fehlgeschlagen")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    store.connect()
    task = None
    if os.environ.get("JARVIS_AUTOPILOT", "1") not in ("0", "false", "nein"):
        task = asyncio.create_task(_autopilot_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Jarvis", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(mobile.router)


# --------------------------------------------------------------------------- Twilio-Signatur
async def _verify_twilio(request: Request) -> dict:
    form = dict(await request.form())
    if not config.VALIDATE_TWILIO:
        return form
    from twilio.request_validator import RequestValidator

    url = config.PUBLIC_URL + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    sig = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(config.TWILIO_AUTH_TOKEN).validate(url, form, sig):
        raise HTTPException(403, "Ungültige Signatur")
    return form


# --------------------------------------------------------------------------- WhatsApp
def _process_whatsapp(sender: str, body: str, media: list[tuple[str, str]]) -> None:
    try:
        if messaging.is_owner(sender):
            reply = agent.handle_owner(body)
            messaging.send_text(sender, reply)
        else:
            reply = agent.handle_candidate(sender, body, media)
            if reply:
                messaging.send_text(sender, reply)
    except Exception as exc:  # noqa: BLE001
        log.exception("WhatsApp-Verarbeitung fehlgeschlagen")
        if messaging.is_owner(sender):
            messaging.notify_owner(f"⚠️ Fehler: {exc}")


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request, bg: BackgroundTasks):
    form = await _verify_twilio(request)
    sender = form.get("From", "")
    body = form.get("Body", "") or ""
    n = int(form.get("NumMedia", "0") or 0)
    media = [(form.get(f"MediaUrl{i}", ""), form.get(f"MediaContentType{i}", "")) for i in range(n)]
    bg.add_task(_process_whatsapp, sender, body, media)  # sofort antworten, Arbeit im Hintergrund
    return Response(EMPTY_TWIML, media_type="application/xml")


# --------------------------------------------------------------------------- Telefon
@app.post("/voice/twiml")
async def voice_twiml(request: Request, call_id: int):
    form = await _verify_twilio(request)
    xml = await asyncio.to_thread(voice.twiml_for, call_id, form.get("AnsweredBy"))
    return Response(xml, media_type="application/xml")


@app.post("/voice/status")
async def voice_status(request: Request, call_id: int):
    form = await _verify_twilio(request)
    status = form.get("CallStatus", "")
    conn = store.connect()
    call = store.get_call(conn, call_id)
    if call and status in ("no-answer", "busy", "failed", "canceled"):
        store.update_call(conn, call_id, status="nicht_erreicht")
    return Response(EMPTY_TWIML, media_type="application/xml")


@app.websocket("/voice/relay")
async def voice_relay(ws: WebSocket):
    await ws.accept()
    session = voice.RelaySession(lambda m: ws.send_text(json.dumps(m)))
    try:
        while True:
            await session.handle(json.loads(await ws.receive_text()))
    except WebSocketDisconnect:
        pass
    finally:
        if session.task and not session.task.done():
            session.task.cancel()
        await asyncio.to_thread(session.finish)


# --------------------------------------------------------------------------- Bewerbungsformular
FORM_CSS = """
:root{--bg:#f5f7fa;--card:#fff;--text:#16202a;--muted:#5d6b78;--line:#d9e0e7;--accent:#0b6e4f;--accent-text:#fff;--err:#b3261e}
@media (prefers-color-scheme: dark){:root{--bg:#10151a;--card:#182027;--text:#e6ebf0;--muted:#9aa8b5;--line:#2a3540;--accent:#3fbf8f;--accent-text:#0b1a14}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,sans-serif;padding:16px}
main{max-width:640px;margin:0 auto}h1{font-size:24px;margin:8px 0 4px}p.lead{color:var(--muted);margin:0 0 20px}
form,.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px}
fieldset{border:0;padding:0;margin:0 0 18px}legend{font-weight:600;margin-bottom:8px}
label{display:block;font-size:14px;color:var(--muted);margin:10px 0 4px}
input[type=text],input[type=email],input[type=tel],select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font-size:16px}
input[type=file]{width:100%;font-size:15px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:520px){.row{grid-template-columns:1fr}}
.check{display:flex;gap:10px;align-items:flex-start;margin:10px 0;color:var(--text);font-size:15px}
.check input{margin-top:4px;width:18px;height:18px;flex:none}
button,.btn{display:inline-block;width:100%;padding:13px;border:0;border-radius:10px;background:var(--accent);color:var(--accent-text);font-size:17px;font-weight:600;cursor:pointer;text-align:center;text-decoration:none}
.small{font-size:13px;color:var(--muted)}.hp{position:absolute;left:-5000px}
"""

_rate: dict[str, deque] = defaultdict(deque)


def _rate_ok(ip: str, limit: int = 5, window: int = 3600) -> bool:
    q = _rate[ip]
    now = time.time()
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>{FORM_CSS}</style></head><body><main>{body}</main></body></html>""")


def _options(items: list[str]) -> str:
    return "".join(f"<option>{html.escape(i)}</option>" for i in items)


@app.get("/")
async def root():
    return RedirectResponse("/bewerbung")


@app.get("/bewerbung", response_class=HTMLResponse)
async def bewerbung_form():
    agency = html.escape(config.AGENCY_NAME)
    body = f"""
<h1>Ihre Stelle in der Schweiz</h1>
<p class="lead">Pflege & Ärzteschaft – wir vermitteln Sie kostenlos an Spitäler, Kliniken und Heime.
In 2 Minuten bewerben, wir melden uns schnell.</p>
<form method="post" action="/bewerbung" enctype="multipart/form-data">
 <fieldset><legend>Kontakt</legend>
  <label for="name">Vor- und Nachname *</label><input id="name" name="name" type="text" required maxlength="120">
  <div class="row">
   <div><label for="phone">Handy (WhatsApp) *</label><input id="phone" name="phone" type="tel" required placeholder="+41 79 … / +49 1…" maxlength="30"></div>
   <div><label for="email">E-Mail</label><input id="email" name="email" type="email" maxlength="120"></div>
  </div>
  <div class="row">
   <div><label for="wohnort">Aktueller Wohnort *</label><input id="wohnort" name="wohnort" type="text" required maxlength="80"></div>
   <div><label for="in_schweiz">Leben Sie in der Schweiz?</label>
    <select id="in_schweiz" name="in_schweiz"><option value="ja">Ja</option><option value="nein">Nein</option></select></div>
  </div>
 </fieldset>
 <fieldset><legend>Beruf</legend>
  <label for="bereich">Bereich / Fachrichtung *</label>
  <select id="bereich" name="bereich" required>
   <optgroup label="Pflege">{_options(NURSING_FIELDS)}</optgroup>
   <optgroup label="Ärztin / Arzt">{_options(["Ärztin/Arzt " + s for s in PHYSICIAN_SPECIALTIES])}</optgroup>
   <option>Anderer Bereich</option>
  </select>
  <div class="row">
   <div><label for="diplom">Diplom / Berufsurkunde vorhanden?</label>
    <select id="diplom" name="diplom"><option value="ja">Ja</option><option value="nein">Nein</option></select></div>
   <div><label for="diplom_land">Land des Diploms</label><input id="diplom_land" name="diplom_land" type="text" maxlength="60"></div>
  </div>
  <div class="row">
   <div><label for="deutsch">Deutschniveau</label>
    <select id="deutsch" name="deutsch"><option>Muttersprache</option><option>C2</option><option>C1</option>
    <option selected>B2</option><option>B1</option><option>A2 oder tiefer</option></select></div>
   <div><label for="anerkennung">Anerkennung in der Schweiz (SRK / MEBEKO)</label>
    <select id="anerkennung" name="anerkennung">
     <option>Anerkennung liegt vor</option><option>Positiver Pre-Check / positiver Zwischenstand</option>
     <option>Verfahren läuft</option><option>Schweizer Diplom (nicht nötig)</option>
     <option>Noch nicht beantragt</option><option>Weiss nicht</option></select></div>
  </div>
  <div class="row">
   <div><label for="verfuegbar">Verfügbar ab</label><input id="verfuegbar" name="verfuegbar" type="text" placeholder="z.B. sofort, 01.03." maxlength="40"></div>
   <div><label for="pensum">Pensum</label><input id="pensum" name="pensum" type="text" placeholder="z.B. 80-100%" maxlength="40"></div>
  </div>
  <label for="cv">Lebenslauf (PDF oder Word, max. 10 MB)</label><input id="cv" name="cv" type="file" accept=".pdf,.docx,.txt">
  <input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
 </fieldset>
 <fieldset><legend>Einwilligung</legend>
  <label class="check"><input type="checkbox" name="consent_data" value="1" required>
   <span>Ich bin einverstanden, dass {agency} meine Angaben zur Stellenvermittlung speichert und anonymisiert an
   mögliche Arbeitgeber weitergibt. Widerruf jederzeit möglich. *</span></label>
  <label class="check"><input type="checkbox" name="consent_whatsapp" value="1" checked>
   <span>Kontakt per WhatsApp ist ok.</span></label>
  <label class="check"><input type="checkbox" name="consent_call" value="1" checked>
   <span>Anruf ist ok – auch durch unseren KI-Telefonassistenten „Jarvis" für ein kurzes Erstgespräch.</span></label>
 </fieldset>
 <button type="submit">Jetzt bewerben</button>
 <p class="small">Mit * markierte Felder sind Pflicht. Für Sie ist die Vermittlung kostenlos.</p>
</form>"""
    return _page("Bewerbung Schweiz", body)


def _evaluate_form(raw: sources.RawProfile) -> None:
    try:
        c = pipeline.evaluate(raw)
    except Exception:  # noqa: BLE001
        log.exception("Formular-Bewertung fehlgeschlagen – Profil liegt in data/inbox")
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (config.INBOX_DIR / f"formular-{datetime.now():%Y%m%d-%H%M%S}.txt").write_text(raw.text, "utf-8")
        return
    conn = store.connect()
    store.upsert(conn, c)
    if c.tier in ("A", "B"):
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        messaging.notify_owner(f"📝 Neue Bewerbung: {a.full_name} – {role}, Tier {c.tier} ({c.score})\n"
                               f"{a.summary}\nID {store.candidate_key(c)}")
        if c.consent_call and voice.within_call_hours():
            # Heisse Bewerber sofort anrufen, solange das Interesse frisch ist
            log.info(voice.place_call("kandidat", store.candidate_key(c)))


@app.post("/bewerbung", response_class=HTMLResponse)
async def bewerbung_submit(
    request: Request, bg: BackgroundTasks,
    name: str = Form(...), phone: str = Form(...), wohnort: str = Form(...), bereich: str = Form(...),
    email: str = Form(""), in_schweiz: str = Form("ja"), diplom: str = Form("ja"),
    diplom_land: str = Form(""), deutsch: str = Form(""), anerkennung: str = Form(""),
    verfuegbar: str = Form(""), pensum: str = Form(""), website: str = Form(""),
    consent_data: str = Form(""), consent_whatsapp: str = Form(""), consent_call: str = Form(""),
    cv: UploadFile | None = File(None),
):
    if website:  # Spam-Bot
        return _page("Danke", "<h1>Danke!</h1>")
    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        raise HTTPException(429, "Zu viele Anfragen")
    if consent_data != "1":
        raise HTTPException(400, "Einwilligung erforderlich")

    cv_text = ""
    if cv is not None and cv.filename:
        data = await cv.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Datei zu gross")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in Path(cv.filename).name if ch.isalnum() or ch in "._-")[:80]
        (UPLOAD_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{safe}").write_bytes(data)
        try:
            cv_text = sources.file_to_text(safe, data) or ""
        except Exception:  # noqa: BLE001
            cv_text = ""

    text = f"""BEWERBUNGSFORMULAR (Angaben der Person selbst)
Name: {name}
Telefon/WhatsApp: {phone}
E-Mail: {email}
Wohnort: {wohnort}
Lebt in der Schweiz: {in_schweiz}
Bereich: {bereich}
Diplom/Urkunde vorhanden: {diplom}
Land des Diploms: {diplom_land}
Deutschniveau: {deutsch}
Anerkennung SRK/MEBEKO: {anerkennung}
Verfügbar ab: {verfuegbar}
Pensum: {pensum}

LEBENSLAUF:
{cv_text or "(kein Lebenslauf hochgeladen)"}"""
    raw = sources.RawProfile(source="Bewerbungsformular", text=text,
                             consent_whatsapp=consent_whatsapp == "1", consent_call=consent_call == "1")
    bg.add_task(_evaluate_form, raw)

    chat = ""
    if config.TWILIO_WHATSAPP_FROM:
        num = "".join(ch for ch in config.TWILIO_WHATSAPP_FROM if ch.isdigit())
        msg = quote(f"Hallo, ich habe mich gerade beworben ({bereich}). Mein Name: {name}")
        chat = (f'<p>Schneller geht\'s per WhatsApp – schreiben Sie uns direkt:</p>'
                f'<a class="btn" href="https://wa.me/{num}?text={msg}">WhatsApp-Chat starten</a>')
    body = f"""<div class="card"><h1>Vielen Dank, {html.escape(name.split()[0])}!</h1>
<p>Wir prüfen Ihre Angaben und melden uns in Kürze{" – eventuell zuerst unser KI-Assistent Jarvis" if consent_call == "1" else ""}.</p>
{chat}</div>"""
    return _page("Danke", body)


# --------------------------------------------------------------------------- Dashboard
@app.get("/shortlist", response_class=HTMLResponse)
async def shortlist(token: str = ""):
    if not config.ADMIN_TOKEN or token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Token fehlt oder falsch (?token=...)")
    conn = store.connect()
    path, _ = report.write(store.todays_shortlist(conn, config.DAILY_SHORTLIST_SIZE))
    return HTMLResponse(path.read_text("utf-8"))


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"
