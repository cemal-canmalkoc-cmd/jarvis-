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
import hashlib
import hmac
import html
import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime
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
    store.apply_settings(store.connect())
    try:
        from . import budget
        budget.ensure_defaults()
        budget.ensure_defaults_v3()
        budget.ensure_defaults_v4()
        budget.ensure_defaults_v5()
        n = store.dedupe_candidates(store.connect())
        if n:
            logging.getLogger("jarvis").info("%s doppelte Kandidaten zusammengeführt", n)
    except Exception:  # noqa: BLE001
        logging.getLogger("jarvis").exception("Standardwerte nicht gesetzt")
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


@app.get("/whatsapp")
async def whatsapp_verify(request: Request):
    """Meta: einmalige Bestätigung der Webhook-Adresse."""
    q = request.query_params
    if (q.get("hub.mode") == "subscribe" and config.META_VERIFY_TOKEN
            and hmac.compare_digest(q.get("hub.verify_token", ""), config.META_VERIFY_TOKEN)):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verifizierung fehlgeschlagen")


def _meta_echoes(payload: dict) -> list[str]:
    """Nachrichten, die du selbst in der WhatsApp-Business-App geschrieben hast (Coexistence-Echo)."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("message_echoes", []) or []:
                if m.get("to"):
                    out.append(m["to"])
    return out


def _meta_messages(payload: dict) -> list[tuple[str, str, list[tuple[str, str]]]]:
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                sender, typ = m.get("from", ""), m.get("type")
                body, media = "", []
                if typ == "text":
                    body = m.get("text", {}).get("body", "")
                elif typ == "button":
                    body = m.get("button", {}).get("text", "")
                elif typ == "interactive":
                    i = m.get("interactive", {})
                    body = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                elif typ == "document":
                    d = m.get("document", {})
                    media.append((f"meta:{d.get('id', '')}", d.get("mime_type", "")))
                    body = d.get("caption", "")
                else:
                    body = "(Nachricht, die Jarvis nicht lesen kann)"
                out.append((sender, body, media))
    return out


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request, bg: BackgroundTasks):
    if request.headers.get("content-type", "").startswith("application/json"):  # Meta Cloud API
        raw = await request.body()
        if config.VALIDATE_TWILIO:
            expected = "sha256=" + hmac.new(config.META_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            if not config.META_APP_SECRET or not hmac.compare_digest(
                    request.headers.get("X-Hub-Signature-256", ""), expected):
                raise HTTPException(403, "Ungültige Signatur")
        payload = json.loads(raw or b"{}")
        for contact in _meta_echoes(payload):
            store.set_state(store.connect(), f"takeover:{store.digits(contact)[-9:]}",
                            datetime.now().isoformat(timespec="minutes"))
        for sender, body, media in _meta_messages(payload):
            bg.add_task(_process_whatsapp, sender, body, media)
        return PlainTextResponse("ok")

    form = await _verify_twilio(request)  # Twilio
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


@app.post("/voice/inbound")
async def voice_inbound(request: Request):
    """Twilio-Nummer → 'A call comes in'. Auch für umgeleitete Anrufe eurer Firmennummer."""
    form = await _verify_twilio(request)
    caller = form.get("From", "")
    xml = await asyncio.to_thread(voice.inbound_twiml, caller)
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
.brand{font-weight:700;color:var(--accent);letter-spacing:.3px;margin-top:4px}
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


LKW_FORM = """
<div class="brand">{agency}</div>
<h1>LKW-Fahrer gesucht 🚛</h1>
<p class="lead">Speditionen in ganz Deutschland suchen Fahrer – Nah- und Fernverkehr.
Für dich kostenlos. In 2 Minuten bewerben, wir melden uns schnell.{contact}</p>
{wa}
<form method="post" action="/bewerbung" enctype="multipart/form-data">
 <input type="hidden" name="in_schweiz" value="nein">
 <fieldset><legend>Kontakt</legend>
  <label for="name">Vor- und Nachname *</label><input id="name" name="name" type="text" required maxlength="120">
  <div class="row">
   <div><label for="phone">Handy (WhatsApp) *</label><input id="phone" name="phone" type="tel" required placeholder="+49 1…" maxlength="30"></div>
   <div><label for="email">E-Mail</label><input id="email" name="email" type="email" maxlength="120"></div>
  </div>
  <label for="wohnort">Wohnort mit PLZ *</label><input id="wohnort" name="wohnort" type="text" required maxlength="80">
 </fieldset>
 <fieldset><legend>Fahrer-Profil</legend>
  <label for="bereich">Was suchst du? *</label>
  <select id="bereich" name="bereich" required>
   <option>LKW-Fahrer Fernverkehr</option><option>LKW-Fahrer Nahverkehr</option>
   <option>LKW-Fahrer Baustelle / Kipper</option><option>LKW-Fahrer Tank / Gefahrgut</option><option>Egal / offen</option>
  </select>
  <div class="row">
   <div><label for="fuehrerschein">Führerschein *</label>
    <select id="fuehrerschein" name="fuehrerschein"><option>CE</option><option>C</option><option>C1E</option><option>C1</option><option>nur B</option></select></div>
   <div><label for="fahrerkarte">Fahrerkarte?</label>
    <select id="fahrerkarte" name="fahrerkarte"><option>ja</option><option>nein</option></select></div>
  </div>
  <div class="row">
   <div><label for="modul95">Modul 95 / Schlüsselzahl 95?</label>
    <select id="modul95" name="modul95"><option>ja</option><option>nein</option><option>weiss nicht</option></select></div>
   <div><label for="adr">ADR-Schein (Gefahrgut)?</label>
    <select id="adr" name="adr"><option>nein</option><option>ja</option></select></div>
  </div>
  <div class="row">
   <div><label for="erfahrung">Jahre Fahrerfahrung</label><input id="erfahrung" name="erfahrung" type="text" maxlength="20"></div>
   <div><label for="deutsch">Deutsch</label>
    <select id="deutsch" name="deutsch"><option>Muttersprache</option><option>C1</option><option selected>B2</option>
    <option>B1</option><option>A2 oder tiefer</option></select></div>
  </div>
  <label for="verfuegbar">Verfügbar ab</label><input id="verfuegbar" name="verfuegbar" type="text" placeholder="z.B. sofort" maxlength="40">
  <label for="cv">Lebenslauf (optional)</label><input id="cv" name="cv" type="file" accept=".pdf,.docx,.txt">
  <input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
 </fieldset>
 <fieldset><legend>Einwilligung</legend>
  <label class="check"><input type="checkbox" name="consent_data" value="1" required>
   <span>Ich bin einverstanden, dass {agency} meine Angaben speichert, mein Profil zunächst anonym passenden
   Arbeitgebern vorstellt und meine Unterlagen an Arbeitgeber weitergibt, die mich kennenlernen möchten.
   Für mich kostenlos. Widerruf jederzeit möglich. *</span></label>
  <label class="check"><input type="checkbox" name="consent_whatsapp" value="1" checked><span>Kontakt per WhatsApp ist ok.</span></label>
  <label class="check"><input type="checkbox" name="consent_call" value="1" checked><span>Anruf ist ok.</span></label>
 </fieldset>
 <button type="submit">Jetzt bewerben</button>
</form>"""


@app.get("/bewerbung", response_class=HTMLResponse)
async def bewerbung_form(bereich: str = ""):
    agency = html.escape(config.AGENCY_NAME)
    if bereich == "lkw":
        from .outreach import contact_number
        num = contact_number()
        contact = (f' Oder direkt per WhatsApp: <a href="https://wa.me/{"".join(ch for ch in num if ch.isdigit())}">'
                   f'{html.escape(num)}</a>') if num else ""
        from .outreach import wa_short
        wa = (f'<a class="btn" style="margin:0 0 16px" href="{wa_short("lkw", "formular")}">💬 Schneller: '
              f'direkt per WhatsApp bewerben</a>' if num else "")
        return _page(f"LKW-Fahrer – {config.AGENCY_NAME}", LKW_FORM.replace("{agency}", agency)
                     .replace("{contact}", contact).replace("{wa}", wa))
    call_hint = ""
    if config.CALL_IN_NUMBER:
        tel = "".join(ch for ch in config.CALL_IN_NUMBER if ch.isdigit() or ch == "+")
        call_hint = (f' Oder einfach anrufen: <a href="tel:{html.escape(tel)}">'
                     f'{html.escape(config.CALL_IN_NUMBER)}</a>')
    from .outreach import contact_number, wa_short
    wa_btn = (f'<a class="btn" style="margin:0 0 16px" href="{wa_short("pflege", "formular")}">💬 Schneller: '
              f'direkt per WhatsApp bewerben</a>' if contact_number() else "")
    body = f"""
<div class="brand">{agency}</div>
<h1>Ihre Stelle in der Schweiz</h1>
<p class="lead">Pflege, Betreuung, Ärzte & weitere medizinische Berufe – wir vermitteln Sie kostenlos an Spitäler,
Kliniken, Heime, Spitex und 24h-Betreuung in der Schweiz.
In 2 Minuten bewerben, wir melden uns schnell.{call_hint}</p>
{wa_btn}
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
    <select id="in_schweiz" name="in_schweiz"><option value="nein" selected>Nein</option><option value="ja">Ja</option></select></div>
  </div>
 </fieldset>
 <fieldset><legend>Beruf</legend>
  <label for="bereich">Bereich / Fachrichtung *</label>
  <select id="bereich" name="bereich" required>
{"".join(f'<optgroup label="{html.escape(g)}">{_options(r)}</optgroup>' for g, r in config.MEDICAL_ROLES.items())}
   <option>Anderer Bereich</option>
  </select>
  <p class="hint" style="font-size:13px;color:var(--muted);margin:4px 0 12px">Die Schweizer Bezeichnung ist eine
   ungefähre Einordnung – verbindlich entscheidet die Anerkennungsstelle (SRK, MEBEKO bzw. SBFI). Wir helfen dabei.</p>
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
   <span>Ich bin einverstanden, dass {agency} meine Angaben speichert und zur Stellensuche an Schweizer
   Partner-Personalvermittler (mit behördlicher Bewilligung) weitergibt. Für mich ist das kostenlos.
   Widerruf jederzeit möglich. *</span></label>
  <label class="check"><input type="checkbox" name="consent_whatsapp" value="1" checked>
   <span>Kontakt per WhatsApp ist ok.</span></label>
  <label class="check"><input type="checkbox" name="consent_call" value="1" checked>
   <span>Anruf ist ok – auch durch unseren KI-Telefonassistenten „Jarvis" für ein kurzes Erstgespräch.</span></label>
 </fieldset>
 <button type="submit">Jetzt bewerben</button>
 <p class="small">Mit * markierte Felder sind Pflicht. Für Sie ist die Vermittlung kostenlos.</p>
</form>"""
    return _page(f"Bewerbung Schweiz – {config.AGENCY_NAME}", body)


def _evaluate_form(raw: sources.RawProfile, cv_path: str | None = None) -> None:
    try:
        c = pipeline.evaluate(raw)
    except Exception:  # noqa: BLE001
        log.exception("Formular-Bewertung fehlgeschlagen – Profil liegt in data/inbox")
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (config.INBOX_DIR / f"formular-{datetime.now():%Y%m%d-%H%M%S}.txt").write_text(raw.text, "utf-8")
        return
    conn = store.connect()
    store.upsert(conn, c)
    key = store.candidate_key(c)
    if cv_path:
        store.set_state(conn, f"cv:{key}", cv_path)
    if c.tier != "X":
        # Wer sich selbst bewirbt, ist interessiert → sofort vermittelbar
        store.set_status(conn, key, "interessiert", "hat sich über das Formular beworben")
        from . import matching
        from .whatsapp import role_phrase
        a = c.assessment
        row = store.get_candidate(conn, key)
        firms = matching.matches(conn, row, 3)
        delivered = matching.auto_deliver()
        lines = [f"📝 NEUER BEWERBER: {a.full_name} – {role_phrase(a)}, {a.current_location or '?'} (Tier {c.tier})",
                 a.summary, "Lebenslauf: " + ("liegt vor ✅" if cv_path else "nicht hochgeladen")]
        if delivered:
            lines.append("📦 Automatisch an Partner geschickt: " + "; ".join(delivered))
        if firms:
            lines.append("🤝 Passende Firmen: " + ", ".join(f"{f['name']} ({f['ort'] or '?'})" for f in firms))
        else:
            lines.append("🔍 Noch keine passende Firma gespeichert – in der App 'Passende Firmen suchen' tippen.")
        from . import deals
        st = store.doc_status(conn, key, a.category)
        if not st["komplett"]:
            lines.append("📄 Fehlende Unterlagen: " + ", ".join(st["fehlt"]) + " – Jarvis fordert sie an.")
            link = deals.whatsapp_to_candidate(row, deals.doc_request_text(row)) if row["consent_whatsapp"] else None
            if link:
                lines.append("Sofort per WhatsApp anfordern: " + link)
        lines.append("👉 App → Kandidaten → 🔥 Interessiert")
        messaging.notify_owner("\n".join(lines))
        if c.consent_call and voice.within_call_hours():
            # Heisse Bewerber sofort anrufen, solange das Interesse frisch ist
            log.info(voice.place_call("kandidat", store.candidate_key(c)))


# --------------------------------------------------------------------------- Direkt in Cemal-Cans WhatsApp
@app.get("/wa")
async def wa_redirect(b: str = "lkw", q: str = "", direkt: str = "", ref: str = "", stelle: int = 0):
    from .outreach import WA_TEXTS, contact_number, wa_link
    if config.CHAT_FIRST and not direkt and b in CHAT_GREETINGS:
        # Selbstständiger Betrieb: Bewerber landen beim KI-Chat statt in deinem WhatsApp
        return RedirectResponse(f"/chat?b={b}&q={quote(q)}", status_code=302)
    if b == "firma" and config.CHAT_FIRST and not direkt:
        return RedirectResponse("/firmen", status_code=302)
    if not contact_number():
        return RedirectResponse("/bewerbung" + ("?bereich=lkw" if b == "lkw" else ""))
    conn = store.connect()
    key = f"clicks:{date.today()}:{b}"
    store.set_state(conn, key, str(int(store.get_state(conn, key) or 0) + 1))
    if q:
        k2 = f"clicks_src:{date.today()}:{q}"
        store.set_state(conn, k2, str(int(store.get_state(conn, k2) or 0) + 1))
    text = WA_TEXTS.get(b, WA_TEXTS["lkw"])
    job = store.get_job(conn, stelle) if stelle else None
    if job:
        text = f"Bewerbung auf Stelle #{job['id']}: {job['title']} ({job['ort']})\n" + text
    ref = "".join(ch for ch in ref if ch.isalnum() or ch in " .-äöüÄÖÜß")[:40].strip()
    if ref:
        text += f"\n(Empfohlen von: {ref})"
        k3 = f"referrals:{date.today()}"
        store.set_state(conn, k3, str(int(store.get_state(conn, k3) or 0) + 1))
    return RedirectResponse(wa_link(text), status_code=302)


# --------------------------------------------------------------------------- Stellenbörse
BEREICH_DE = {"lkw": "LKW-Fahrer", "pflege": "Pflege", "arzt": "Ärzte"}


def _job_card(j: dict) -> str:
    e = html.escape
    return (f'<a class="card" style="display:block;text-decoration:none;color:inherit;margin-bottom:12px" '
            f'href="/jobs/{j["id"]}"><b>{e(j["title"])}</b><div class="lead" style="margin:4px 0 0">📍 {e(j["ort"] or "")}'
            f'{" · 💶 " + e(j["gehalt"]) if j["gehalt"] else ""} · {BEREICH_DE.get(j["bereich"], "")}</div></a>')


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_list(b: str = ""):
    conn = store.connect()
    items = [j for j in store.jobs(conn) if not b or j["bereich"] == b]
    body = "".join(_job_card(j) for j in items) or "<p class='lead'>Gerade keine offenen Stellen – bewirb dich trotzdem initiativ.</p>"
    return _page(f"Stellen – {config.AGENCY_NAME}", f"""<div class="brand">{html.escape(config.AGENCY_NAME)}</div>
<h1>Offene Stellen</h1>
<p class="lead">Bewerbung in 1 Minute per WhatsApp – für Bewerber kostenlos.</p>
{body}
<a class="btn" href="/bewerbung">Initiativ bewerben</a>""")


@app.get("/jobs/{jid}", response_class=HTMLResponse)
async def job_detail(jid: int):
    e = html.escape
    j = store.get_job(store.connect(), jid)
    if not j or not j["active"]:
        return RedirectResponse("/jobs", status_code=302)
    b = j["bereich"] if j["bereich"] in BEREICH_DE else "pflege"
    apply = f"{config.PUBLIC_URL}/wa?b={b}&q=job{j['id']}&stelle={j['id']}&direkt=1"
    country = "DE" if b == "lkw" else "CH"
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": j["title"],
          "description": (j["beschreibung"] or j["title"]).replace("\n", "<br>"),
          "datePosted": j["created"], "employmentType": "FULL_TIME",
          "hiringOrganization": {"@type": "Organization", "name": config.AGENCY_NAME, "sameAs": config.PUBLIC_URL},
          "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": j["ort"] or "",
                                                        "addressCountry": country}},
          "directApply": True}
    ld_tag = ("" if j.get("auto_key") else
              f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>')
    return _page(f"{j['title']} – {config.AGENCY_NAME}", f"""{ld_tag}
<div class="brand">{e(config.AGENCY_NAME)}</div>
<h1>{e(j['title'])}</h1>
<p class="lead">📍 {e(j['ort'] or '')}{' · 💶 ' + e(j['gehalt']) if j['gehalt'] else ''}</p>
<div class="card" style="white-space:pre-wrap">{e(j['beschreibung'] or '')}</div>
<p class="lead">✅ Für dich kostenlos · ✅ Bewerbung in 1 Minute: Lebenslauf oder Führerschein als Foto per WhatsApp</p>
<a class="btn" href="{e(apply)}">💬 Jetzt per WhatsApp bewerben</a>
<a class="btn" style="margin-top:8px;background:transparent;color:var(--accent);border:1px solid var(--line)"
   href="/bewerbung{'?bereich=lkw' if b == 'lkw' else ''}">Oder Online-Formular</a>
<p style="margin-top:16px"><a href="/jobs">← Alle Stellen</a></p>""")


# --------------------------------------------------------------------------- Empfehlungsprogramm
@app.get("/empfehlen", response_class=HTMLResponse)
async def empfehlen(b: str = "lkw"):
    """„Fahrer werben Fahrer“: Bewerber teilen ihren persönlichen Link mit Kollegen."""
    b = b if b in ("lkw", "pflege", "arzt") else "lkw"
    who = {"lkw": "LKW-Fahrer", "pflege": "Pflegekräfte", "arzt": "Ärztinnen und Ärzte"}[b]
    amount = {"lkw": config.REFERRAL_BONUS_LKW, "pflege": config.REFERRAL_BONUS_PFLEGE,
              "arzt": config.REFERRAL_BONUS_ARZT}[b] or config.REFERRAL_BONUS
    bonus = (f"<p class='lead'>🎁 Als Dankeschön: <b>{html.escape(amount)}</b>, wenn deine Empfehlung bei uns eine "
             f"Stelle antritt und die Probezeit besteht.</p>" if amount else "")
    share_intro = {"lkw": "Hey, ich hab hier was für Fahrer: Hansa Personal vermittelt LKW-Fahrer kostenlos an "
                          "Speditionen. Einfach Führerschein oder Lebenslauf per WhatsApp schicken:",
                   "pflege": "Hallo, kennst du schon Hansa Personal? Sie vermitteln Pflegekräfte kostenlos in die "
                             "Schweiz und helfen bei der Anerkennung:",
                   "arzt": "Hallo, Hansa Personal vermittelt Ärztinnen und Ärzte kostenlos in die Schweiz:"}[b]
    return _page(f"Empfehlen – {config.AGENCY_NAME}", f"""<div class="brand">{html.escape(config.AGENCY_NAME)}</div>
<h1>Kennst du {who}, die eine neue Stelle suchen?</h1>
<p class="lead">Schick ihnen deinen persönlichen Link – sie melden sich mit einem Tipp per WhatsApp. Für sie kostenlos.</p>
{bonus}
<fieldset><legend>Dein persönlicher Link</legend>
<label for="n">Dein Name (damit wir wissen, von wem die Empfehlung kommt)</label>
<input id="n" type="text" maxlength="40" placeholder="z. B. Ali K.">
<a class="btn" id="share" href="#">💬 Per WhatsApp an Kollegen schicken</a>
</fieldset>
<script>
const base = {json.dumps(config.PUBLIC_URL + "/wa?b=" + b + "&q=empfehlung")}, intro = {json.dumps(share_intro)};
document.getElementById("share").onclick = e => {{
  const n = document.getElementById("n").value.trim();
  const link = base + (n ? "&ref=" + encodeURIComponent(n) : "");
  e.currentTarget.href = "https://wa.me/?text=" + encodeURIComponent(intro + " " + link);
}};
</script>""")


# --------------------------------------------------------------------------- KI-Chat für Bewerber (rund um die Uhr)
CHAT_GREETINGS = {
    "lkw": "Hallo! 👋 Ich bin Jarvis, der KI-Assistent von {agency}. Wir vermitteln LKW-Fahrer an Speditionen in "
           "ganz Deutschland – für dich kostenlos. Welchen Führerschein hast du (C oder CE)?",
    "arzt": "Guten Tag! Ich bin Jarvis, der KI-Assistent von {agency}. Wir vermitteln Ärztinnen und Ärzte an "
            "Kliniken in der Schweiz – für Sie kostenlos. In welcher Fachrichtung sind Sie tätig?",
    "pflege": "Guten Tag! Ich bin Jarvis, der KI-Assistent von {agency}. Wir vermitteln Pflegefachpersonen an "
              "Spitäler, Kliniken und Heime in der Schweiz – für Sie kostenlos. Was ist Ihr Beruf bzw. Ihr Abschluss?",
}

CHAT_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chat – {agency}</title>
<style>{css}
main{{display:flex;flex-direction:column;height:calc(100dvh - 32px)}}
#log{{flex:1;overflow-y:auto;padding:4px 0}}
.m{{max-width:85%;padding:10px 14px;border-radius:16px;margin:6px 0;white-space:pre-wrap;word-wrap:break-word}}
.b{{background:var(--card);border:1px solid var(--line)}} .u{{background:var(--accent);color:var(--accent-text);margin-left:auto}}
#f{{display:flex;gap:8px;padding:8px 0 0;margin:0;background:none;border:0;box-shadow:none;max-width:100%}}
#t{{flex:1;min-width:0;padding:12px;border-radius:12px;border:1px solid var(--line);
background:var(--card);color:var(--text);font:inherit}} #f button{{flex-shrink:0;width:auto;margin:0;padding:0 18px;border:0;border-radius:12px;
background:var(--accent);color:var(--accent-text);font:inherit;font-weight:600}}
.hint{{font-size:13px;color:var(--muted);text-align:center;margin:4px 0}}
</style></head><body><main>
<div class="brand">{agency}</div>
<div id="log"></div>
<form id="f"><input id="t" autocomplete="off" maxlength="1500" placeholder="Nachricht schreiben …" required>
<button>Senden</button></form>
<p class="hint">KI-Assistent · Ihre Angaben werden nur mit Ihrer Zustimmung an Arbeitgeber weitergegeben ·
<a href="/datenschutz">Datenschutz</a>{wa}</p>
</main><script>
const B={b}, G={greeting};
let sid; try {{ sid = localStorage.getItem("jchat"); }} catch (e) {{}}
if (!sid) {{ sid = Array.from(crypto.getRandomValues(new Uint8Array(12)), x => x.toString(16).padStart(2,"0")).join("");
  try {{ localStorage.setItem("jchat", sid); }} catch (e) {{}} }}
const log = document.getElementById("log");
function add(t, cls) {{ const d = document.createElement("div"); d.className = "m " + cls; d.textContent = t;
  log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }}
add(G, "b");
document.getElementById("f").onsubmit = async (e) => {{
  e.preventDefault(); const i = document.getElementById("t"); const text = i.value.trim(); if (!text) return;
  i.value = ""; add(text, "u"); const w = add("…", "b");
  try {{
    const r = await fetch("/chat/nachricht", {{method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{sid, text, b: B}})}});
    const j = await r.json(); w.textContent = j.antwort || "Bitte später nochmal versuchen.";
  }} catch (err) {{ w.textContent = "Verbindung unterbrochen – bitte nochmal senden."; }}
  log.scrollTop = log.scrollHeight;
}};
</script></body></html>"""


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(b: str = "pflege", q: str = ""):
    from .outreach import contact_number, wa_short
    b = b if b in CHAT_GREETINGS else "pflege"
    conn = store.connect()
    key = f"chat_opens:{date.today()}:{b}"
    store.set_state(conn, key, str(int(store.get_state(conn, key) or 0) + 1))
    greeting = CHAT_GREETINGS[b].replace("{agency}", config.AGENCY_NAME)
    wa = (f' · <a href="{wa_short(b, q or "chat")}&direkt=1">lieber persönlich per WhatsApp</a>'
          if contact_number() else "")
    return HTMLResponse(CHAT_PAGE.format(agency=html.escape(config.AGENCY_NAME), css=FORM_CSS, wa=wa,
                                         b=json.dumps(b), greeting=json.dumps(greeting)))


@app.post("/chat/nachricht")
async def chat_message(request: Request):
    import re as _re
    from . import convo
    ip = request.client.host if request.client else "?"
    if not _rate_ok("chat:" + ip, limit=60):
        return {"antwort": "Bitte einen Moment warten und dann nochmal schreiben."}
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Ungültige Anfrage")
    sid, text, b = str(data.get("sid", "")), str(data.get("text", "")).strip()[:1500], str(data.get("b", "pflege"))
    if not _re.fullmatch(r"[0-9a-f]{16,40}", sid) or not text:
        raise HTTPException(400, "Ungültige Anfrage")
    cid = f"web:{sid}"
    conn = store.connect()
    if not store.get_convo(conn, cid):
        greeting = CHAT_GREETINGS.get(b, CHAT_GREETINGS["pflege"]).replace("{agency}", config.AGENCY_NAME)
        store.save_convo(conn, cid, "kandidat", [
            {"role": "user", "content": f"(Person öffnet den Chat auf der Webseite, Bereich: {b})"},
            {"role": "assistant", "content": greeting}])
    reply = await asyncio.to_thread(convo.candidate_turn, cid, text, "Web-Chat")
    return {"antwort": reply}


@app.get("/datenschutz", response_class=HTMLResponse)
async def datenschutz():
    e = html.escape
    kontakt = config.SMTP_FROM or config.SMTP_USER or config.OWNER_EMAIL or ""
    return _page("Datenschutz", f"""<div class="card"><h1>Datenschutz</h1>
<p><b>Verantwortlich:</b> {e(config.RECRUITER_NAME)}, {e(config.AGENCY_NAME)}{(", " + e(config.FIRMA_ADRESSE)) if config.FIRMA_ADRESSE else ""}
{("· E-Mail: " + e(kontakt)) if kontakt else ""}</p>
<p><b>Zweck:</b> Wir verarbeiten Ihre Angaben (Kontaktdaten, beruflicher Werdegang, Unterlagen), um Ihnen passende
Stellen zu vermitteln. Grundlage ist Ihre Einwilligung bzw. Ihre Anfrage (Art. 6 Abs. 1 a und b DSGVO).</p>
<p><b>Weitergabe:</b> Ihr Profil geht zunächst nur anonym an Arbeitgeber. Name, Kontaktdaten und Unterlagen geben wir
erst weiter, wenn Sie zugestimmt haben und ein Arbeitgeber Interesse zeigt.</p>
<p><b>KI-Assistent:</b> Chat und E-Mail-Antworten werden von einem KI-Assistenten erstellt. Dafür werden die Nachrichten
an den KI-Dienst Anthropic (USA) übermittelt und dort verarbeitet.</p>
<p><b>Speicherdauer:</b> bis zum Ende der Vermittlung bzw. bis zu Ihrem Widerruf, höchstens 2 Jahre.</p>
<p><b>Ihre Rechte:</b> Auskunft, Berichtigung, Löschung, Einschränkung, Widerspruch, Datenübertragbarkeit und
Beschwerde bei einer Aufsichtsbehörde. Eine kurze Nachricht „STOP“ oder „Bitte löschen“ genügt.</p></div>""")


# --------------------------------------------------------------------------- Firmen-Seite (eigener Vertrieb)
FIRMEN_FORM = """
<div class="brand">{agency}</div>
<h1>Personal gesucht? Wir liefern.</h1>
<p class="lead"><b>LKW-Fahrer (C/CE, Modul 95, ADR)</b> in ganz Deutschland und <b>Pflegefachkräfte & Ärzte</b>
für die Schweiz – geprüft, mit Unterlagen, kurzfristig verfügbar. <b>Sie zahlen nur bei Einstellung.</b></p>
{wa}
<form method="post" action="/firmen">
 <fieldset><legend>Ihre Anfrage (1 Minute)</legend>
  <label for="firma">Firma *</label><input id="firma" name="firma" required maxlength="120">
  <div class="row">
   <div><label for="ort">Ort *</label><input id="ort" name="ort" required maxlength="80"></div>
   <div><label for="kontakt">Ansprechperson</label><input id="kontakt" name="kontakt" maxlength="80"></div>
  </div>
  <div class="row">
   <div><label for="email">E-Mail *</label><input id="email" name="email" type="email" required maxlength="120"></div>
   <div><label for="telefon">Telefon</label><input id="telefon" name="telefon" type="tel" maxlength="30"></div>
  </div>
  <label for="bereich">Wen suchen Sie? *</label>
  <select id="bereich" name="bereich"><option value="lkw">LKW-Fahrer</option><option value="pflege">Pflegefachkräfte (Schweiz)</option>
   <option value="arzt">Ärztinnen/Ärzte (Schweiz)</option></select>
  <label for="bedarf">Details (Anzahl, Nah-/Fernverkehr, ADR, Start …)</label><input id="bedarf" name="bedarf" maxlength="300">
  <input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
 </fieldset>
 <label class="check"><input type="checkbox" name="consent" value="1" required>
  <span>Bitte senden Sie mir passende Kandidatenprofile und Ihre Konditionen per E-Mail. *</span></label>
 <button type="submit">Kandidaten anfordern</button>
 <p class="small">Erfolgshonorar – keine Vorabkosten, keine Abo-Gebühren.</p>
</form>"""


@app.get("/firmen", response_class=HTMLResponse)
async def firmen_seite():
    from .outreach import contact_number, wa_short
    wa = (f'<a class="btn" style="margin:0 0 16px" href="{wa_short("firma", "web")}">💬 Direkt per WhatsApp anfragen</a>'
          if contact_number() else "")
    return _page(f"Personal für Ihr Unternehmen – {config.AGENCY_NAME}",
                 FIRMEN_FORM.replace("{agency}", html.escape(config.AGENCY_NAME)).replace("{wa}", wa))


def _handle_firm_lead(cid: int) -> None:
    from . import deals
    try:
        msg = deals.send_agreement_and_profiles(cid)
    except Exception as exc:  # noqa: BLE001
        msg = f"E-Mail nicht gesendet: {exc}"
    firm = store.get_company(store.connect(), cid)
    messaging.notify_owner(f"🏢🔥 NEUE FIRMENANFRAGE: {firm['name']} ({firm['city']})\nSucht: {firm['needs']}\n"
                           f"Kontakt: {firm['contact_name'] or '-'} {firm['email']} {firm['phone'] or ''}\n{msg}\n"
                           f"👉 Jetzt anrufen – heisse Anfrage!")


@app.post("/firmen", response_class=HTMLResponse)
async def firmen_anfrage(request: Request, bg: BackgroundTasks, firma: str = Form(...), ort: str = Form(...),
                         email: str = Form(...), bereich: str = Form("lkw"), kontakt: str = Form(""),
                         telefon: str = Form(""), bedarf: str = Form(""), website: str = Form(""),
                         consent: str = Form("")):
    if website:
        return _page("Danke", "<h1>Danke!</h1>")
    ip = request.client.host if request.client else "?"
    if not _rate_ok("firm:" + ip):
        raise HTTPException(429, "Zu viele Anfragen")
    if consent != "1":
        raise HTTPException(400, "Einwilligung erforderlich")
    label = {"lkw": "LKW-Fahrer", "pflege": "Pflegefachkräfte", "arzt": "Ärztinnen/Ärzte"}.get(bereich, bereich)
    conn = store.connect()
    store.add_company(conn, name=firma.strip(), city=ort.strip(), phone=telefon or None,
                      needs=f"{label}: {bedarf}".strip(": "), source_url="Firmen-Seite", email=email,
                      branche="lkw" if bereich == "lkw" else "gesundheit")
    cid = conn.execute("SELECT id FROM companies WHERE name=? AND city IS ?", (firma.strip(), ort.strip())).fetchone()[0]
    store.set_company_contact(conn, cid, email, kontakt or None)
    store.set_company_status(conn, cid, "interessiert", "Anfrage über die Firmen-Seite")
    bg.add_task(_handle_firm_lead, cid)
    return _page("Danke", f'<div class="card"><h1>Vielen Dank!</h1><p>Sie erhalten in Kürze passende Profile und '
                          f'unsere Konditionen an {html.escape(email)}. {html.escape(config.RECRUITER_NAME)} meldet sich '
                          f'zusätzlich persönlich.</p></div>')


# --------------------------------------------------------------------------- Dokumente hochladen (Kandidat)
@app.get("/dokumente", response_class=HTMLResponse)
async def dokumente_form(k: str = "", t: str = ""):
    from . import deals
    conn = store.connect()
    row = store.get_candidate(conn, k)
    if not row or not deals.check_token(row["key"], t):
        raise HTTPException(404, "Link ungültig")
    a = store.load(row).assessment
    cat = a.category if a.category in store.DOC_TYPES else "pflege"
    st = store.doc_status(conn, row["key"], a.category)
    fields = "".join(
        f'<label for="{typ}">{"✅ " if typ in st["vorhanden"] else ""}{html.escape(label)}</label>'
        f'<input id="{typ}" name="{typ}" type="file" accept="image/*,.pdf,.docx" multiple>'
        for typ, label in store.DOC_TYPES[cat].items())
    first = html.escape(a.full_name.split()[0]) if a.full_name and a.full_name.lower() != "unbekannt" else ""
    body = f"""<div class="brand">{html.escape(config.AGENCY_NAME)}</div>
<h1>Ihre Unterlagen{', ' + first if first else ''}</h1>
<p class="lead">Fotos mit dem Handy reichen völlig. Danach stelle ich Sie sofort passenden Arbeitgebern vor.</p>
<form method="post" action="/dokumente?k={html.escape(row['key'])}&t={html.escape(t)}" enctype="multipart/form-data">
<fieldset>{fields}</fieldset>
<label class="check"><input type="checkbox" name="consent" value="1" required>
<span>Ich bin einverstanden, dass {html.escape(config.AGENCY_NAME)} meine Unterlagen an Arbeitgeber weitergibt,
die mich kennenlernen möchten. *</span></label>
<button type="submit">Hochladen</button></form>"""
    return _page("Unterlagen hochladen", body)


@app.post("/dokumente", response_class=HTMLResponse)
async def dokumente_upload(request: Request, k: str = "", t: str = ""):
    from . import deals
    conn = store.connect()
    row = store.get_candidate(conn, k)
    if not row or not deals.check_token(row["key"], t):
        raise HTTPException(404, "Link ungültig")
    ip = request.client.host if request.client else "?"
    if not _rate_ok("doc:" + ip, limit=20):
        raise HTTPException(429, "Zu viele Anfragen")
    form = await request.form()
    if form.get("consent") != "1":
        raise HTTPException(400, "Einwilligung erforderlich")
    a = store.load(row).assessment
    cat = a.category if a.category in store.DOC_TYPES else "pflege"
    saved = 0
    folder = UPLOAD_DIR / row["key"]
    folder.mkdir(parents=True, exist_ok=True)
    for typ in store.DOC_TYPES[cat]:
        for f in form.getlist(typ):
            if not getattr(f, "filename", None):
                continue
            data = await f.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                continue
            safe = "".join(ch for ch in Path(f.filename).name if ch.isalnum() or ch in "._-")[:60] or "datei"
            path = folder / f"{datetime.now():%Y%m%d-%H%M%S}-{typ}-{safe}"
            path.write_bytes(data)
            store.add_document(conn, row["key"], typ, str(path))
            saved += 1
    st = store.doc_status(conn, row["key"], a.category)
    messaging.notify_owner(f"📄 {a.full_name}: {saved} Dokument(e) hochgeladen – "
                           + ("✅ Unterlagen KOMPLETT, bereit zum Vorstellen!" if st["komplett"]
                              else "fehlt noch: " + ", ".join(st["fehlt"])))
    msg = ("Vielen Dank! Ihre Unterlagen sind komplett – ich melde mich in Kürze mit passenden Stellen."
           if st["komplett"] else "Danke! Es fehlt noch: " + ", ".join(st["fehlt"]) + ". Sie können diesen Link jederzeit wieder öffnen.")
    return _page("Danke", f'<div class="card"><h1>Danke!</h1><p>{html.escape(msg)}</p></div>')


@app.post("/bewerbung", response_class=HTMLResponse)
async def bewerbung_submit(
    request: Request, bg: BackgroundTasks,
    name: str = Form(...), phone: str = Form(...), wohnort: str = Form(...), bereich: str = Form(...),
    email: str = Form(""), in_schweiz: str = Form("ja"), diplom: str = Form("ja"),
    diplom_land: str = Form(""), deutsch: str = Form(""), anerkennung: str = Form(""),
    verfuegbar: str = Form(""), pensum: str = Form(""), website: str = Form(""),
    consent_data: str = Form(""), consent_whatsapp: str = Form(""), consent_call: str = Form(""),
    fuehrerschein: str = Form(""), fahrerkarte: str = Form(""), modul95: str = Form(""), adr: str = Form(""),
    erfahrung: str = Form(""),
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
    cv_file = None
    if cv is not None and cv.filename:
        data = await cv.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Datei zu gross")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in Path(cv.filename).name if ch.isalnum() or ch in "._-")[:80]
        cv_file = UPLOAD_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{safe}"
        cv_file.write_bytes(data)
        try:
            cv_text = sources.file_to_text(safe, data) or ""
        except Exception:  # noqa: BLE001
            cv_text = ""

    if fuehrerschein:
        text = f"""BEWERBUNGSFORMULAR LKW-FAHRER (Angaben der Person selbst)
Name: {name}
Telefon/WhatsApp: {phone}
E-Mail: {email}
Wohnort: {wohnort} (Deutschland)
Gesucht: {bereich}
Führerscheinklasse: {fuehrerschein}
Fahrerkarte: {fahrerkarte}
Modul 95 / Schlüsselzahl 95: {modul95}
ADR-Schein: {adr}
Jahre Fahrerfahrung: {erfahrung}
Deutsch: {deutsch}
Verfügbar ab: {verfuegbar}

LEBENSLAUF:
{cv_text or "(kein Lebenslauf hochgeladen)"}"""
    else:
        text = None
    text = text or f"""BEWERBUNGSFORMULAR (Angaben der Person selbst)
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
    raw.file = None
    bg.add_task(_evaluate_form, raw, str(cv_file) if cv_file else None)

    chat = ""
    from .outreach import contact_number
    num = "".join(ch for ch in contact_number() if ch.isdigit()) or messaging.jarvis_number()
    if num:
        msg = quote(f"Hallo, ich habe mich gerade beworben ({bereich}). Mein Name: {name}")
        chat = (f'<p>Schneller geht\'s per WhatsApp – schreiben Sie uns direkt:</p>'
                f'<a class="btn" href="https://wa.me/{num}?text={msg}">WhatsApp-Chat starten</a>')
    if config.CALL_IN_NUMBER:
        tel = "".join(ch for ch in config.CALL_IN_NUMBER if ch.isdigit() or ch == "+")
        chat += (f'<p style="margin-top:16px">Lieber telefonieren? Rufen Sie uns an:</p>'
                 f'<a class="btn" style="background:var(--card);color:var(--accent);border:1px solid var(--line)" '
                 f'href="tel:{html.escape(tel)}">📞 {html.escape(config.CALL_IN_NUMBER)}</a>')
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
