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

from . import brain, config, messaging, store
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

    if call["target_type"] == "kandidat":
        _, greeting = candidate_context(store.get_candidate(conn, call["target_key"]))
    else:
        _, greeting = company_context(store.get_company(conn, int(call["target_key"])))

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
            if call["target_type"] == "kandidat":
                self.system, greeting = candidate_context(store.get_candidate(conn, call["target_key"]))
            else:
                self.system, greeting = company_context(store.get_company(conn, int(call["target_key"])))
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
