"""Telefon-Agent: Jarvis ruft Kandidaten und Arbeitgeber an und führt das Gespräch selbst.

Technik: Twilio Voice + ConversationRelay (Spracherkennung und Sprachausgabe bei Twilio).
Jarvis bekommt den gesprochenen Text über einen WebSocket, antwortet mit Claude (gestreamt)
und Twilio liest die Antwort vor.

Leitplanken (fest eingebaut):
- Jarvis sagt im ersten Satz, dass er ein KI-Assistent ist (EU AI Act, Transparenzpflicht).
- Kandidaten nur mit Einwilligung (Formular oder eigene Bewerbung), nie Opt-out-Nummern.
- Anrufe nur Mo-Fr in den Geschäftszeiten.
- Anrufbeantworter → sofort auflegen.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from . import brain, config, messaging, pricing, store
from .whatsapp import normalize_phone, role_phrase

log = logging.getLogger("jarvis.voice")
HANGUP = "[AUFLEGEN]"
END_DELAY_S = 4.0  # Zeit, damit die Verabschiedung noch ausgesprochen wird

_async_client: anthropic.AsyncAnthropic | None = None


def aclient() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic()
    return _async_client


# --------------------------------------------------------------------------- Regeln
def within_call_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo(config.TIMEZONE))
    return now.weekday() < 5 and config.CALL_HOURS[0] <= now.hour < config.CALL_HOURS[1]


def e164(phone: str | None) -> str | None:
    d = normalize_phone(phone)
    return f"+{d}" if d else None


# --------------------------------------------------------------------------- Gesprächsleitfäden
PHONE_STYLE = """Telefon-Stil:
- Du sprichst Hochdeutsch, freundlich, Sie-Form. Kurze Sätze, höchstens 2 Sätze pro Antwort.
- Keine Aufzählungen, kein Markdown, keine Emojis. Zahlen ausschreiben, wenn es natürlicher klingt.
- Stelle immer nur EINE Frage auf einmal und warte die Antwort ab.
- Du bist ein KI-Assistent und gibst dich niemals als Mensch aus. Fragt jemand, bestätige es.
- Versprich keine konkrete Stelle, keinen Lohn und keine Anerkennung.
- Wenn die Person nicht sprechen möchte, keine Zeit hat oder nicht mehr angerufen werden will:
  freundlich bestätigen und das Gespräch beenden.
- Wenn das Gespräch beendet ist, verabschiede dich und schreibe ganz am Ende {hangup}."""


def candidate_context(row) -> tuple[str, str]:
    c = store.load(row)
    a = c.assessment
    role = role_phrase(a)
    rec = "SRK" if a.category == "pflege" else "MEBEKO"
    greeting = (f"Grüezi, hier ist Jarvis, der digitale KI-Assistent von {config.AGENCY_NAME}. "
                f"Ich rufe wegen Ihres Profils als {role} an. Passt es Ihnen gerade für zwei, drei Minuten?")
    system = f"""Du bist Jarvis, der KI-Telefonassistent von {config.AGENCY_NAME}. Du rufst im Auftrag von
{config.RECRUITER_NAME} eine Kandidatin / einen Kandidaten an.

{config.REQUIREMENTS_TEXT}

Was wir bereits wissen (aus dem Lebenslauf, kann veraltet sein):
- Name: {a.full_name}
- Bereich: {role}
- Diplom/Urkunde: {a.has_diploma_certificate} (Land: {a.diploma_country})
- Deutsch: {a.german_level}
- {rec}-Status: {a.recognition_status}
- Wohnort: {a.current_location}
- Offene Punkte: {"; ".join(c.missing) or "keine"}

Ziel des Anrufs:
1. Interesse an einer Stelle in der Schweiz klären.
2. Offene Punkte kurz bestätigen: Diplom, Deutsch-Zertifikat (mind. B2), {rec}-Stand,
   ab wann verfügbar, Wunschregion, Pensum.
3. Bei Interesse: einen Rückruf mit {config.RECRUITER_NAME} vereinbaren (Tag und Uhrzeit erfragen)
   und fragen, ob wir die Unterlagen per WhatsApp anfordern dürfen.
4. Fragen, ob wir das Profil an unsere Schweizer Partner-Personalvermittlung weitergeben dürfen.

Du hast das Gespräch bereits begonnen mit: "{greeting}"

{PHONE_STYLE.format(hangup=HANGUP)}"""
    return system, greeting


def company_context(row) -> tuple[str, str]:
    conn = store.connect()
    top = store.todays_shortlist(conn, 8)
    pitch = []
    for c in top:
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        pitch.append(f"- {role or a.category}, Deutsch {a.german_level}, Anerkennung: {a.recognition_status}")
    greeting = (f"Grüezi, hier ist Jarvis, ein digitaler KI-Assistent der Personalvermittlung "
                f"{config.AGENCY_NAME}. Dürfte ich kurz mit der Person sprechen, die bei Ihnen "
                f"für die Rekrutierung in der Pflege oder bei den Ärzten zuständig ist?")
    system = f"""Du bist Jarvis, der KI-Telefonassistent der Personalvermittlung {config.AGENCY_NAME}
(Ansprechperson: {config.RECRUITER_NAME}). Du rufst einen möglichen Kunden an.

Arbeitgeber: {row["name"]} in {row["city"] or "?"}
Bekannte offene Stellen: {row["needs"] or "unbekannt"}

Unsere aktuell verfügbaren, vorqualifizierten Kandidaten (NUR anonym erwähnen, niemals Namen nennen):
{chr(10).join(pitch) or "- laufend neue Pflegefachpersonen und Ärzte mit SRK- bzw. MEBEKO-Anerkennung"}

{pricing.phone_text()}

Ziel des Anrufs:
1. Zur zuständigen Person (HR / Pflegedienstleitung / Chefarzt-Sekretariat) verbinden lassen
   oder deren Namen und E-Mail erfragen.
2. Aktuellen Personalbedarf in Pflege und Ärzteschaft erfragen.
3. Anbieten, passende anonymisierte Kandidatenprofile per E-Mail zu senden. E-Mail-Adresse erfragen
   und zur Sicherheit buchstabieren lassen.
4. Wenn grundsätzlich keine Personalvermittler gewünscht sind: höflich akzeptieren,
   zusichern, dass wir nicht mehr anrufen, und beenden.

Du hast das Gespräch bereits begonnen mit: "{greeting}"

{PHONE_STYLE.format(hangup=HANGUP)}"""
    return system, greeting


def inbound_context(call) -> tuple[str, str]:
    """Eingehender Anruf: Jarvis ist die Telefonzentrale von Hansa Personal."""
    conn = store.connect()
    known = ""
    cand = store.find_candidate_by_phone(conn, call["phone"])
    if cand:
        c = store.load(cand)
        known = (f"Die Nummer gehört vermutlich zu einem bekannten Kandidaten: {c.assessment.full_name}, "
                 f"{role_phrase(c.assessment)}, Status {cand['status']}. Bestätige kurz den Namen.")
    else:
        firm = next((f for f in conn.execute("SELECT * FROM companies WHERE phone IS NOT NULL").fetchall()
                     if store.digits(f["phone"])[-9:] == store.digits(call["phone"])[-9:]), None)
        if firm:
            known = f"Die Nummer gehört vermutlich zum Arbeitgeber {firm['name']} ({firm['city'] or '?'})."
    greeting = (f"Grüezi, Sie sind bei {config.AGENCY_NAME}. Hier spricht Jarvis, der digitale "
                f"KI-Assistent. Wie kann ich Ihnen helfen?")
    system = f"""Du bist Jarvis, die KI-Telefonzentrale der Personalvermittlung {config.AGENCY_NAME}
(Inhaber/Ansprechperson: {config.RECRUITER_NAME}). Jemand ruft UNS an.

{config.REQUIREMENTS_TEXT}

{known}

Finde zuerst heraus, wer anruft:
A) KANDIDAT (sucht eine Stelle): Erfrage nacheinander Vor- und Nachname, Beruf bzw. Fachrichtung,
   Diplom/Urkunde, Deutsch-Zertifikat (mind. B2), Stand SRK- bzw. MEBEKO-Anerkennung, Wohnort,
   ab wann verfügbar, Wunschregion und Pensum. Frage, ob wir per WhatsApp schreiben dürfen
   (für den Lebenslauf), und ob die E-Mail-Adresse für Unterlagen gewünscht ist (buchstabieren lassen).
B) ARBEITGEBER (sucht Personal): Erfrage Firma, Ort, Name und Funktion der Ansprechperson,
   welche Stellen (Bereich, Anzahl, Pensum, Start) und die E-Mail-Adresse (buchstabieren lassen).
   Sage zu, dass sich {config.RECRUITER_NAME} bzw. unsere Schweizer Partner-Personalvermittlung persönlich
   zurückmeldet, und frage nach einer guten Rückrufzeit. Schliesse selbst keine Vereinbarung ab.
C) SONSTIGES: Anliegen und Rückrufnummer aufnehmen, Rückruf durch {config.RECRUITER_NAME} zusagen.

{pricing.phone_text()}

Wenn jemand ausdrücklich {config.RECRUITER_NAME} persönlich sprechen will: Nimm das Anliegen auf und
sage einen Rückruf so bald wie möglich zu.

Du hast das Gespräch bereits begonnen mit: "{greeting}"

{PHONE_STYLE.format(hangup=HANGUP)}"""
    return system, greeting


def context_for(conn, call) -> tuple[str, str]:
    if call["target_type"] == "kandidat":
        return candidate_context(store.get_candidate(conn, call["target_key"]))
    if call["target_type"] == "firma":
        return company_context(store.get_company(conn, int(call["target_key"])))
    return inbound_context(call)


# --------------------------------------------------------------------------- Anruf starten
def place_call(target_type: str, target_key: str, force_hours: bool = False) -> str:
    """Startet einen Anruf. Gibt eine Statusmeldung zurück (für den Owner-Chat)."""
    conn = store.connect()
    if not force_hours and not within_call_hours():
        return "Ausserhalb der Anrufzeiten (Mo-Fr 9-18 Uhr). Anruf nicht gestartet."
    if target_type == "kandidat":
        row = store.get_candidate(conn, target_key)
        if not row:
            return f"Kandidat {target_key} nicht gefunden."
        if not row["consent_call"]:
            return (f"{row['name']}: keine Anruf-Einwilligung (z.B. Web-Fund). "
                    f"Bitte manuell per WhatsApp-Link kontaktieren.")
        phone, label = row["phone"], row["name"]
    elif target_type == "firma":
        row = store.get_company(conn, int(target_key))
        if not row:
            return f"Firma {target_key} nicht gefunden."
        if row["status"] == "nicht_anrufen":
            return f"{row['name']} möchte nicht angerufen werden."
        phone, label = row["phone"], row["name"]
    else:
        return "Unbekannter Anruftyp."

    number = e164(phone)
    if not number:
        return f"{label}: keine gültige Telefonnummer."
    if store.is_opted_out(conn, number):
        return f"{label} steht auf der Sperrliste (nicht anrufen)."
    if not config.TWILIO_VOICE_FROM:
        return "TWILIO_VOICE_FROM ist nicht gesetzt – Telefonie nicht eingerichtet."

    call_id = store.create_call(conn, target_type, target_key, number)
    call = messaging.twilio().calls.create(
        to=number,
        from_=config.TWILIO_VOICE_FROM,
        url=f"{config.PUBLIC_URL}/voice/twiml?call_id={call_id}",
        machine_detection="Enable",
        status_callback=f"{config.PUBLIC_URL}/voice/status?call_id={call_id}",
        status_callback_event=["completed"],
        time_limit=900,
    )
    store.update_call(conn, call_id, call_sid=call.sid, status="läuft")
    if target_type == "firma":
        store.set_company_status(conn, int(target_key), "angerufen")
    return f"Rufe {label} an ({number}) – Anruf-ID {call_id}."


def twiml_for(call_id: int, answered_by: str | None) -> str:
    from twilio.twiml.voice_response import Connect, ConversationRelay, VoiceResponse

    conn = store.connect()
    call = store.get_call(conn, call_id)
    resp = VoiceResponse()
    if call is None:
        resp.hangup()
        return str(resp)
    if answered_by and (answered_by.startswith("machine") or answered_by == "fax"):
        store.update_call(conn, call_id, status="anrufbeantworter")
        resp.hangup()
        return str(resp)

    _, greeting = context_for(conn, call)
    return _relay_twiml(call_id, greeting)


def inbound_twiml(from_number: str) -> str:
    """Eingehender Anruf (auch umgeleitet von eurer Firmennummer): Jarvis nimmt ab."""
    conn = store.connect()
    number = e164(from_number) or from_number or "unbekannt"
    call_id = store.create_call(conn, "eingehend", "", number)
    store.update_call(conn, call_id, status="läuft")
    _, greeting = inbound_context(store.get_call(conn, call_id))
    return _relay_twiml(call_id, greeting)


def _relay_twiml(call_id: int, greeting: str) -> str:
    from twilio.twiml.voice_response import Connect, ConversationRelay, VoiceResponse

    resp = VoiceResponse()
    ws_url = config.PUBLIC_URL.replace("https://", "wss://").replace("http://", "ws://") + "/voice/relay"
    opts = {"url": ws_url, "language": config.VOICE_LANGUAGE, "welcome_greeting": greeting}
    if config.VOICE_TTS_PROVIDER:
        opts["tts_provider"] = config.VOICE_TTS_PROVIDER
    if config.VOICE_NAME:
        opts["voice"] = config.VOICE_NAME
    connect = Connect()
    relay = ConversationRelay(**opts)
    relay.parameter(name="call_id", value=str(call_id))
    connect.append(relay)
    resp.append(connect)
    return str(resp)


# --------------------------------------------------------------------------- Live-Gespräch
class _HangupFilter:
    """Lässt Text durch, hält aber [AUFLEGEN] zurück, auch wenn es über mehrere Tokens verteilt ist."""

    def __init__(self) -> None:
        self.buf = ""
        self.hangup = False

    def feed(self, token: str) -> str:
        self.buf += token
        if HANGUP in self.buf:
            self.hangup = True
            self.buf = self.buf.replace(HANGUP, "")
        idx = self.buf.rfind("[")
        if idx != -1 and HANGUP.startswith(self.buf[idx:]):
            out, self.buf = self.buf[:idx], self.buf[idx:]
            return out
        out, self.buf = self.buf, ""
        return out

    def flush(self) -> str:
        out = self.buf.replace(HANGUP, "")
        self.buf = ""
        return out


class RelaySession:
    def __init__(self, send_json) -> None:
        self.send_json = send_json
        self.call_id: int | None = None
        self.system = ""
        self.messages: list = []
        self.transcript: list[dict] = []
        self.pending_user = ""
        self.task: asyncio.Task | None = None
        self.ended = False

    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "setup":
            params = msg.get("customParameters") or {}
            self.call_id = int(params.get("call_id", 0))
            conn = store.connect()
            call = store.get_call(conn, self.call_id)
            self.system, greeting = context_for(conn, call)
            self.transcript.append({"jarvis": greeting})
            store.update_call(conn, self.call_id, status="verbunden")
        elif t == "prompt":
            text = msg.get("voicePrompt", "")
            self.transcript.append({"gegenueber": text})
            self.pending_user = (self.pending_user + " " + text).strip()
            if self.task and not self.task.done():
                self.task.cancel()
            self.task = asyncio.create_task(self._respond())
        elif t == "interrupt":
            heard = msg.get("utteranceUntilInterrupt", "")
            if self.task and not self.task.done():
                self.task.cancel()
            if heard:
                self.pending_user = (f"(Du wurdest unterbrochen; gehört wurde nur: \"{heard}\") "
                                     + self.pending_user).strip()
        elif t == "error":
            log.error("ConversationRelay-Fehler: %s", msg)

    async def _respond(self) -> None:
        user_text = self.pending_user
        self.messages.append({"role": "user", "content": user_text})
        filt = _HangupFilter()
        spoken = ""
        try:
            kwargs = dict(
                model=config.MODEL, max_tokens=2000, system=self.system,
                output_config={"effort": config.VOICE_EFFORT}, messages=self.messages,
                **brain.fallback_kwargs(config.MODEL),
            )
            if config.VOICE_FAST_MODE:
                kwargs["speed"] = "fast"
            api = aclient().beta.messages if "betas" in kwargs else aclient().messages
            async with api.stream(**kwargs) as stream:
                async for token in stream.text_stream:
                    out = filt.feed(token)
                    if out:
                        spoken += out
                        await self.send_json({"type": "text", "token": out, "last": False})
                final = await stream.get_final_message()
        except asyncio.CancelledError:
            self.messages.pop()  # Antwort wurde unterbrochen → Nutzertext bleibt offen
            raise
        except anthropic.APIError as exc:
            log.error("Claude-Fehler im Anruf %s: %s", self.call_id, exc)
            self.messages.pop()
            await self.send_json({"type": "text", "token": "Entschuldigung, einen Moment bitte.",
                                  "last": True})
            return

        # Verlauf zuerst festschreiben, damit eine Unterbrechung ihn nicht halb zurücklässt
        self.messages.append({"role": "assistant", "content": final.content})
        self.pending_user = ""
        tail = filt.flush()
        spoken += tail
        self.transcript.append({"jarvis": spoken.strip()})
        await self.send_json({"type": "text", "token": tail, "last": True})
        if filt.hangup or final.stop_reason == "refusal":
            self.ended = True
            await asyncio.sleep(END_DELAY_S)
            await self.send_json({"type": "end", "handoffData": json.dumps({"reason": "fertig"})})

    def finish(self) -> None:
        if self.call_id:
            finalize_call(self.call_id, self.transcript)


# --------------------------------------------------------------------------- Nach dem Anruf
OUTCOME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome": {"type": "string", "enum": [
            "interessiert", "rueckruf", "kein_interesse", "nicht_anrufen", "ungeeignet",
            "kein_bedarf", "nicht_erreicht"]},
        "summary": {"type": "string"},
        "next_step": {"type": "string"},
        "callback_time": {"type": ["string", "null"]},
        "contact_name": {"type": ["string", "null"]},
        "contact_email": {"type": ["string", "null"]},
        "german_level": {"type": ["string", "null"]},
        "recognition_status": {"type": ["string", "null"]},
        "availability": {"type": ["string", "null"]},
    },
    "required": ["outcome", "summary", "next_step", "callback_time", "contact_name",
                 "contact_email", "german_level", "recognition_status", "availability"],
}


def summarize(target_type: str, transcript: list[dict]) -> dict:
    lines = "\n".join(f"{k.upper()}: {v}" for turn in transcript for k, v in turn.items())
    resp = brain.create(
        model=config.MODEL, max_tokens=4000,
        system=("Fasse ein Telefonat einer Personalvermittlung zusammen. Nur belegte Fakten. "
                "summary: 2-3 Sätze Deutsch. next_step: konkrete nächste Aktion für den Recruiter. "
                "Outcome 'nicht_anrufen', wenn die Person keine weiteren Anrufe möchte."),
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": OUTCOME_SCHEMA}},
        messages=[{"role": "user", "content": f"Anruf an: {target_type}\n\nTranskript:\n{lines}"}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


INBOUND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "anrufer_typ": {"type": "string", "enum": ["kandidat", "arbeitgeber", "sonstiges"]},
        "name": {"type": ["string", "null"]},
        "firma": {"type": ["string", "null"]},
        "ort": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "bedarf": {"type": ["string", "null"]},
        "interessiert": {"type": "boolean"},
        "whatsapp_ok": {"type": ["boolean", "null"]},
        "rueckruf_zeit": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "next_step": {"type": "string"},
    },
    "required": ["anrufer_typ", "name", "firma", "ort", "email", "bedarf", "interessiert",
                 "whatsapp_ok", "rueckruf_zeit", "summary", "next_step"],
}


def summarize_inbound(transcript: list[dict]) -> dict:
    lines = "\n".join(f"{k.upper()}: {v}" for turn in transcript for k, v in turn.items())
    resp = brain.create(
        model=config.MODEL, max_tokens=4000,
        system=("Werte einen eingehenden Anruf bei einer Personalvermittlung aus. Nur belegte Fakten. "
                "bedarf: bei Arbeitgebern die gesuchten Stellen, bei Kandidaten Beruf/Fachrichtung. "
                "summary: 2-3 Sätze Deutsch. next_step: konkrete Aktion für den Recruiter."),
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": INBOUND_SCHEMA}},
        messages=[{"role": "user", "content": f"Transkript:\n{lines}"}],
    )
    return json.loads("".join(b.text for b in resp.content if b.type == "text"))


def finalize_inbound(call, transcript: list[dict]) -> None:
    from . import matching, pipeline, sources

    conn = store.connect()
    r = summarize_inbound(transcript)
    store.update_call(conn, call["id"], status=f"eingehend_{r['anrufer_typ']}",
                      summary=json.dumps(r, ensure_ascii=False),
                      transcript=json.dumps(transcript, ensure_ascii=False))
    phone = call["phone"]
    cb = f"\nRückruf: {r['rueckruf_zeit']}" if r.get("rueckruf_zeit") else ""

    if r["anrufer_typ"] == "kandidat":
        row = store.find_candidate_by_phone(conn, phone)
        if row is None:
            lines = "\n".join(f"{k}: {v}" for t in transcript for k, v in t.items())
            raw = sources.RawProfile(
                source=f"Anruf von {phone}",
                text=f"Telefon: {phone}\nE-Mail: {r.get('email') or ''}\n\nTelefonat mit Jarvis:\n{lines}",
                consent_call=True, consent_whatsapp=bool(r.get("whatsapp_ok")))
            c = pipeline.evaluate(raw)
            store.upsert(conn, c)
            row = store.get_candidate(conn, store.candidate_key(c))
        if r["interessiert"]:
            store.set_status(conn, row["key"], "interessiert", r["summary"])
            matching.auto_deliver()
        c = store.load(row)
        if r.get("whatsapp_ok"):
            # Gespräch auf WhatsApp weiterführen (Lebenslauf anfordern) – Vorlage nötig, da Erstkontakt
            try:
                if messaging.send_first_contact_template(phone, c.assessment.full_name.split()[0],
                                                         role_phrase(c.assessment)):
                    store.grant_whatsapp_consent(conn, row["key"])
            except Exception as exc:  # noqa: BLE001
                log.error("WhatsApp nach Anruf fehlgeschlagen: %s", exc)
        messaging.notify_owner(
            f"☎️🔥 Kandidat hat angerufen: {c.assessment.full_name} – {role_phrase(c.assessment)}, "
            f"Tier {c.tier} ({c.score})\n{r['summary']}\nNächster Schritt: {r['next_step']}{cb}\n"
            f"Tel: {phone} · ID {row['key'][:6]}")
    elif r["anrufer_typ"] == "arbeitgeber":
        name = r.get("firma") or f"Anrufer {phone}"
        store.add_company(conn, name=name, city=r.get("ort"), phone=phone, needs=r.get("bedarf"),
                          source_url="eingehender Anruf")
        firm = conn.execute("SELECT id FROM companies WHERE name=? AND city IS ?", (name, r.get("ort"))).fetchone()
        if firm:
            store.set_company_status(conn, firm["id"], "interessiert", r["summary"])
            store.set_company_contact(conn, firm["id"], r.get("email"), r.get("name"))
        messaging.notify_owner(
            f"☎️🏥🔥 ARBEITGEBER hat angerufen: {name} ({r.get('ort') or '?'})\n"
            f"Kontakt: {r.get('name') or '?'} {r.get('email') or ''}\nBedarf: {r.get('bedarf') or '?'}\n"
            f"{r['summary']}{cb}\n👉 Bitte zurückrufen: {phone}")
    else:
        messaging.notify_owner(f"☎️ Anruf von {phone}: {r['summary']}{cb}\nNächster Schritt: {r['next_step']}")


def finalize_call(call_id: int, transcript: list[dict]) -> None:
    conn = store.connect()
    call = store.get_call(conn, call_id)
    if call is None:
        return
    spoke = any("gegenueber" in t for t in transcript)
    if not spoke:
        store.update_call(conn, call_id, status=call["status"] if call["status"] == "anrufbeantworter"
                          else "nicht_erreicht", transcript=json.dumps(transcript, ensure_ascii=False))
        return
    if call["target_type"] == "eingehend":
        try:
            finalize_inbound(call, transcript)
        except Exception as exc:  # noqa: BLE001
            log.exception("Auswertung eingehender Anruf fehlgeschlagen")
            store.update_call(conn, call_id, status="eingehend",
                              transcript=json.dumps(transcript, ensure_ascii=False))
            messaging.notify_owner(f"☎️ Anruf von {call['phone']} – Auswertung fehlgeschlagen ({exc}). "
                                   "Bitte zurückrufen.")
        return
    try:
        result = summarize(call["target_type"], transcript)
    except Exception as exc:  # noqa: BLE001
        log.error("Zusammenfassung fehlgeschlagen: %s", exc)
        result = {"outcome": "rueckruf", "summary": "Zusammenfassung fehlgeschlagen – Transkript prüfen.",
                  "next_step": "Transkript lesen"}
    store.update_call(conn, call_id, status=result["outcome"], summary=json.dumps(result, ensure_ascii=False),
                      transcript=json.dumps(transcript, ensure_ascii=False))

    outcome = result["outcome"]
    if call["target_type"] == "kandidat":
        row = store.get_candidate(conn, call["target_key"])
        name = row["name"] if row else "?"
        status = {"interessiert": "interessiert", "rueckruf": "interessiert",
                  "kein_interesse": "kein_interesse", "nicht_anrufen": "kein_interesse",
                  "ungeeignet": "kein_interesse"}.get(outcome, "kontaktiert")
        store.set_status(conn, call["target_key"], status, result["summary"])
        if outcome == "nicht_anrufen":
            store.add_optout(conn, call["phone"])
        if status == "interessiert":
            from . import matching
            matching.auto_deliver()
        icon = "🔥" if outcome in ("interessiert", "rueckruf") else "📞"
        messaging.notify_owner(
            f"{icon} Anruf Kandidat: {name}\nErgebnis: {outcome}\n{result['summary']}\n"
            f"Nächster Schritt: {result['next_step']}"
            + (f"\nRückruf: {result['callback_time']}" if result.get("callback_time") else "")
            + f"\nID: {call['target_key']}")
    else:
        cid = int(call["target_key"])
        row = store.get_company(conn, cid)
        status = {"interessiert": "interessiert", "rueckruf": "interessiert",
                  "kein_bedarf": "kein_bedarf", "kein_interesse": "kein_bedarf",
                  "nicht_anrufen": "nicht_anrufen"}.get(outcome, "angerufen")
        note = result["summary"]
        if result.get("contact_email"):
            note += f" | Kontakt: {result.get('contact_name') or ''} {result['contact_email']}"
        store.set_company_status(conn, cid, status, note)
        if result.get("contact_email") or result.get("contact_name"):
            store.set_company_contact(conn, cid, result.get("contact_email"), result.get("contact_name"))
        if outcome == "nicht_anrufen":
            store.add_optout(conn, call["phone"])
        icon = "🏥🔥" if status == "interessiert" else "🏥"
        messaging.notify_owner(
            f"{icon} Anruf Firma: {row['name'] if row else cid}\nErgebnis: {outcome}\n{result['summary']}\n"
            f"Nächster Schritt: {result['next_step']}"
            + (f"\nKontakt: {result.get('contact_name') or ''} {result['contact_email']}"
               if result.get("contact_email") else ""))
