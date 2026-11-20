"""Jarvis per WhatsApp steuern.

- Owner-Agent: Du schreibst Jarvis Befehle in normaler Sprache ("ruf die Top 5 an",
  "such Firmen in Bern mit Bedarf Psychiatrie", "wie viele haben wir heute?").
- Kandidaten-Agent: Kandidaten, die Jarvis per WhatsApp schreiben, bekommen sofort Antwort,
  werden vorqualifiziert und können ihren Lebenslauf schicken.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta

import anthropic
import requests

from . import brain, companies, config, matching, messaging, pipeline, pricing, sources, store, voice

log = logging.getLogger("jarvis.agent")

# --------------------------------------------------------------------------- Werkzeuge
def _role(c) -> str:
    a = c.assessment
    return (a.physician_specialty if a.category == "arzt" else a.nursing_field) or a.category


def t_tagesbericht() -> dict:
    s = store.stats_today(store.connect())
    s["ziel_pro_tag"] = config.DAILY_TARGET
    return s


def t_suche_starten(web: bool = True, fokus: list[str] | None = None) -> dict:
    return pipeline.run(use_web=web, web_focuses=fokus or None)


def t_shortlist(anzahl: int = 20) -> list[dict]:
    conn = store.connect()
    out = []
    for c in store.todays_shortlist(conn, anzahl):
        row = store.get_candidate(conn, store.candidate_key(c))
        out.append({"id": store.candidate_key(c), "name": c.assessment.full_name, "tier": c.tier,
                    "score": c.score, "bereich": _role(c), "deutsch": c.assessment.german_level,
                    "anerkennung": c.assessment.recognition_status,
                    "ort": c.assessment.current_location,
                    "darf_anrufen": bool(row["consent_call"]) if row else False,
                    "whatsapp_link": c.whatsapp_link})
    return out


def t_kandidat(id: str) -> dict:
    conn = store.connect()
    row = store.get_candidate(conn, id)
    if not row:
        return {"fehler": "nicht gefunden"}
    c = store.load(row)
    calls = conn.execute("SELECT started, status, summary FROM calls WHERE target_key=? "
                         "AND target_type='kandidat'", (id,)).fetchall()
    return {"id": id, "status": row["status"], "notizen": row["notes"],
            "darf_anrufen": bool(row["consent_call"]), "darf_whatsapp": bool(row["consent_whatsapp"]),
            "telefon": c.assessment.phone, "bewertung": c.model_dump(mode="json"),
            "anrufe": [dict(r) for r in calls]}


def t_status_setzen(id: str, status: str, notiz: str = "") -> str:
    store.set_status(store.connect(), id, status, notiz)
    return "ok"


def t_kandidat_anrufen(id: str) -> str:
    return voice.place_call("kandidat", id)


def t_anrufrunde_kandidaten(anzahl: int = 5) -> list[str]:
    conn = store.connect()
    return [voice.place_call("kandidat", r["key"]) for r in store.callable_candidates(conn, anzahl)] \
        or ["Keine anrufbaren Kandidaten (mit Einwilligung) offen."]


def t_firmen_suchen(fokus: str, region: str = "Deutschschweiz") -> dict:
    return companies.find(fokus, region)


def t_firmen_liste(status: str | None = None, anzahl: int = 20) -> list[dict]:
    return [dict(r) for r in store.list_companies(store.connect(), status, anzahl)]


def t_firma_anrufen(id: int) -> str:
    return voice.place_call("firma", str(id))


def t_anrufrunde_firmen(anzahl: int = 5) -> list[str]:
    conn = store.connect()
    return [voice.place_call("firma", str(r["id"])) for r in store.callable_companies(conn, anzahl)] \
        or ["Keine offenen Firmen mit Telefonnummer."]


def t_firma_status(id: int, status: str, notiz: str = "") -> str:
    store.set_company_status(store.connect(), id, status, notiz)
    return "ok"


def t_whatsapp_an_kandidat(id: str, text: str) -> str:
    conn = store.connect()
    row = store.get_candidate(conn, id)
    if not row:
        return "Kandidat nicht gefunden."
    c = store.load(row)
    if store.is_opted_out(conn, row["phone"]):
        return "Kandidat hat Kontakt abgelehnt (Sperrliste)."
    _, updated = store.load_chat(conn, row["phone"])
    session_open = bool(updated) and datetime.fromisoformat(updated) > datetime.now() - timedelta(hours=23)
    if row["consent_whatsapp"] and session_open:
        messaging.send_text(row["phone"], text)
        store.set_status(conn, id, "kontaktiert", "WhatsApp gesendet")
        return "Gesendet."
    if row["consent_whatsapp"] and messaging.send_first_contact_template(
            row["phone"], c.assessment.full_name.split()[0], _role(c)):
        store.set_status(conn, id, "kontaktiert", "WhatsApp-Vorlage gesendet")
        return "Erstkontakt-Vorlage gesendet (freier Text erst nach Antwort möglich)."
    return f"Automatisch nicht erlaubt (keine WhatsApp-Einwilligung). Manuell senden: {c.whatsapp_link}"


def t_passende_firmen(id: str) -> list[dict] | str:
    conn = store.connect()
    row = store.get_candidate(conn, id)
    return matching.matches(conn, row) if row else "Kandidat nicht gefunden."


def t_kandidat_vorstellen(id: str, firma_id: int) -> str:
    conn = store.connect()
    row = store.get_candidate(conn, id)
    return matching.present(row["key"], firma_id) if row else "Kandidat nicht gefunden."


def t_firma_kontakt(id: int, email: str, name: str = "") -> str:
    store.set_company_contact(store.connect(), id, email, name or None)
    return "ok"


def t_nachfassen() -> list[dict]:
    rows = store.followups_due(store.connect())
    return [{"id": r["key"], "name": r["name"], "zuletzt": r["last_contact"], "telefon": r["phone"]}
            for r in rows] or [{"info": "Niemand muss heute nachgefasst werden."}]


def t_kunde_anlegen(name: str, ort: str = "", email: str = "", ansprechperson: str = "",
                    telefon: str = "", bedarf: str = "") -> str:
    cid = store.add_customer(store.connect(), name, ort or None, email or None, ansprechperson or None,
                             telefon or None, bedarf or None)
    hint = "" if email else " Ohne E-Mail kann ich nicht automatisch liefern – bitte nachreichen."
    hint += (" Tipp: Bewilligung des Partners im SECO-Verzeichnis prüfen (www.avg-seco.admin.ch) "
             "und eine schriftliche Kooperationsvereinbarung abschliessen.")
    return f"Kunde gespeichert (Firma {cid}).{hint}"


def t_kunden_liste() -> list[dict]:
    conn = store.connect()
    out = []
    for k in store.customers(conn):
        n = conn.execute("SELECT COUNT(*) FROM presentations WHERE company_id=?", (k["id"],)).fetchone()[0]
        out.append({"id": k["id"], "name": k["name"], "ort": k["city"], "bedarf": k["needs"],
                    "email": k["email"], "ansprechperson": k["contact_name"], "vorgestellt": n})
    return out or [{"info": "Noch keine Kunden hinterlegt."}]


def t_preis_setzen(bereich: str, modell: str, wert: float, garantie_monate: int = 0, notiz: str = "") -> str:
    store.set_price(store.connect(), bereich, modell, wert, garantie_monate, notiz)
    return f"{bereich}: {pricing.overview()[bereich]}"


def t_preise_anzeigen() -> dict:
    return pricing.overview()


def t_kunden_beliefern() -> list[str]:
    return matching.auto_deliver() or ["Gerade nichts zu liefern (keine neuen interessierten, passenden Kandidaten)."]


def t_kandidat_hinzufuegen(angaben: str, whatsapp_ok: bool = False, anruf_ok: bool = False) -> dict:
    """Kandidat aus frei geschriebenen Angaben oder eingefügtem Lebenslauf anlegen und bewerten."""
    raw = sources.RawProfile(source="Eingabe Cemal-Can", text=angaben,
                             consent_whatsapp=whatsapp_ok, consent_call=anruf_ok)
    c = pipeline.evaluate(raw)
    store.upsert(store.connect(), c)
    return {"id": store.candidate_key(c)[:6], "name": c.assessment.full_name, "tier": c.tier,
            "score": c.score, "fehlt": c.missing, "whatsapp_link": c.whatsapp_link}


def t_inserat_schreiben(zielgruppe: str = "", plattform: str = "Facebook-Gruppe") -> str:
    from . import ads
    return ads.write_ad(zielgruppe or None, plattform)


def t_inserat_posten(text: str = "", zielgruppe: str = "") -> str:
    from . import ads
    if not ads.facebook_ready():
        return ("Facebook-Seite noch nicht verbunden (META_PAGE_ID/META_PAGE_TOKEN fehlen). "
                "Text zum manuellen Posten:\n\n" + (text or ads.write_ad(zielgruppe or None)))
    text = text or ads.write_ad(zielgruppe or None)
    return f"✅ Auf der Facebook-Seite gepostet (ID {ads.post_facebook_page(text)})."


def t_update() -> dict:
    from . import updater
    return updater.update(force=True)


def t_autopilot_jetzt() -> dict:
    from . import autopilot
    return autopilot.morning(force=True)


TOOLS = {
    "tagesbericht": (t_tagesbericht, "Zahlen von heute: neue/vermittelbare Kandidaten, Anrufe, Firmen.", {}),
    "suche_starten": (t_suche_starten, "Kandidatensuche jetzt starten (Ordner, E-Mail, optional Web). "
                      "Dauert mehrere Minuten.",
                      {"web": {"type": "boolean"},
                       "fokus": {"type": "array", "items": {"type": "string"},
                                 "description": "z.B. ['Pflegefachfrau Psychiatrie Zürich']"}}),
    "shortlist": (t_shortlist, "Beste offene Kandidaten (Tier A/B) mit WhatsApp-Links.",
                  {"anzahl": {"type": "integer"}}),
    "kandidat": (t_kandidat, "Alle Details zu einem Kandidaten.", {"id": {"type": "string"}}),
    "status_setzen": (t_status_setzen, "Kandidatenstatus setzen.",
                      {"id": {"type": "string"},
                       "status": {"type": "string", "enum": list(store.STATUSES)},
                       "notiz": {"type": "string"}}),
    "kandidat_anrufen": (t_kandidat_anrufen, "Jarvis ruft einen Kandidaten an (KI-Telefonat).",
                         {"id": {"type": "string"}}),
    "anrufrunde_kandidaten": (t_anrufrunde_kandidaten, "Ruft die besten noch nicht angerufenen "
                              "Kandidaten mit Einwilligung an.", {"anzahl": {"type": "integer"}}),
    "firmen_suchen": (t_firmen_suchen, "Sucht Arbeitgeber mit offenen Stellen im Web. Dauert Minuten.",
                      {"fokus": {"type": "string"}, "region": {"type": "string"}}),
    "firmen_liste": (t_firmen_liste, "Gespeicherte Arbeitgeber anzeigen.",
                     {"status": {"type": "string", "enum": list(store.COMPANY_STATUSES)},
                      "anzahl": {"type": "integer"}}),
    "firma_anrufen": (t_firma_anrufen, "Jarvis ruft einen Arbeitgeber an.", {"id": {"type": "integer"}}),
    "anrufrunde_firmen": (t_anrufrunde_firmen, "Ruft die nächsten offenen Arbeitgeber an.",
                          {"anzahl": {"type": "integer"}}),
    "firma_status": (t_firma_status, "Arbeitgeberstatus setzen.",
                     {"id": {"type": "integer"},
                      "status": {"type": "string", "enum": list(store.COMPANY_STATUSES)},
                      "notiz": {"type": "string"}}),
    "whatsapp_an_kandidat": (t_whatsapp_an_kandidat, "WhatsApp an Kandidaten (nur mit Einwilligung, "
                             "sonst kommt ein Link zum manuellen Senden zurück).",
                             {"id": {"type": "string"}, "text": {"type": "string"}}),
    "passende_firmen": (t_passende_firmen, "Arbeitgeber, die zu einem Kandidaten passen.",
                        {"id": {"type": "string"}}),
    "kandidat_vorstellen": (t_kandidat_vorstellen, "Interessierten Kandidaten einer Firma anonym per E-Mail "
                            "vorstellen (nur nach Zusage des Kandidaten).",
                            {"id": {"type": "string"}, "firma_id": {"type": "integer"}}),
    "firma_kontakt": (t_firma_kontakt, "E-Mail/Ansprechperson einer Firma speichern.",
                      {"id": {"type": "integer"}, "email": {"type": "string"}, "name": {"type": "string"}}),
    "nachfassen": (t_nachfassen, "Kandidaten, die seit 3+ Tagen nicht geantwortet haben.", {}),
    "kunde_anlegen": (t_kunde_anlegen, "Partner-Vermittler (Schweizer Personalvermittlung mit Bewilligung, "
                      "an die Hansa Kandidaten liefert) anlegen oder aktualisieren.",
                      {"name": {"type": "string"}, "ort": {"type": "string"}, "email": {"type": "string"},
                       "ansprechperson": {"type": "string"}, "telefon": {"type": "string"},
                       "bedarf": {"type": "string", "description": "z.B. '2 Dipl. Pflegefachpersonen Psychiatrie 80-100%'"}}),
    "kunden_liste": (t_kunden_liste, "Alle Bestandskunden mit Bedarf und Anzahl vorgestellter Kandidaten.", {}),
    "kunden_beliefern": (t_kunden_beliefern, "Interessierte Kandidaten jetzt an passende Kunden liefern.", {}),
    "preis_setzen": (t_preis_setzen, "Vermittlungshonorar für einen Bereich festlegen (nur auf Anweisung von Cemal-Can).",
                     {"bereich": {"type": "string", "enum": list(store.PRICE_AREAS)},
                      "modell": {"type": "string", "enum": list(store.PRICE_MODELS)},
                      "wert": {"type": "number", "description": "Prozent (z.B. 18) oder CHF-Betrag"},
                      "garantie_monate": {"type": "integer"}, "notiz": {"type": "string"}}),
    "preise_anzeigen": (t_preise_anzeigen, "Aktuelle Honorare je Bereich.", {}),
    "kandidat_hinzufuegen": (t_kandidat_hinzufuegen, "Kandidat aus Text anlegen (Notizen, Telefonat, eingefügter "
                             "Lebenslauf), sofort bewerten und speichern.",
                             {"angaben": {"type": "string"},
                              "whatsapp_ok": {"type": "boolean", "description": "Person hat WhatsApp-Kontakt erlaubt"},
                              "anruf_ok": {"type": "boolean", "description": "Person hat Anruf erlaubt"}}),
    "inserat_schreiben": (t_inserat_schreiben, "Neues Stelleninserat schreiben (für Gruppen, Instagram, Kleinanzeigen …).",
                          {"zielgruppe": {"type": "string"}, "plattform": {"type": "string"}}),
    "inserat_posten": (t_inserat_posten, "Inserat sofort auf der Facebook-Seite von Hansa Personal veröffentlichen.",
                       {"text": {"type": "string", "description": "leer = Jarvis schreibt selbst"},
                        "zielgruppe": {"type": "string"}}),
    "jarvis_aktualisieren": (t_update, "Neueste Jarvis-Version von GitHub installieren und neu starten.", {}),
    "autopilot_jetzt": (t_autopilot_jetzt, "Kompletten Tagesablauf sofort ausführen.", {}),
}

REQUIRED = {"kandidat_hinzufuegen": ["angaben"], "kunde_anlegen": ["name"], "preis_setzen": ["bereich", "modell", "wert"],
            "passende_firmen": ["id"], "kandidat_vorstellen": ["id", "firma_id"],
            "firma_kontakt": ["id", "email"], "kandidat": ["id"], "status_setzen": ["id", "status"], "kandidat_anrufen": ["id"],
            "firmen_suchen": ["fokus"], "firma_anrufen": ["id"], "firma_status": ["id", "status"],
            "whatsapp_an_kandidat": ["id", "text"]}

TOOL_DEFS = [
    {"name": n, "description": d,
     "input_schema": {"type": "object", "properties": props, "required": REQUIRED.get(n, [])}}
    for n, (_, d, props) in TOOLS.items()
]


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    fn = TOOLS.get(name, (None,))[0]
    if fn is None:
        return f"Unbekanntes Werkzeug {name}", True
    try:
        return json.dumps(fn(**args), ensure_ascii=False, default=str)[:20000], False
    except Exception as exc:  # noqa: BLE001
        log.exception("Werkzeug %s fehlgeschlagen", name)
        return f"Fehler: {exc}", True


def _dump(content) -> list[dict]:
    return [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else b for b in content]


def _fingerprint(system: str) -> str:
    import hashlib
    return hashlib.sha256(f"{config.MODEL}|{system}".encode()).hexdigest()[:16]


def _conversation(conn, phone: str, max_age_h: int, system: str) -> list:
    """Bisheriger Verlauf – aber nur, wenn Modell und Anweisungen gleich geblieben sind.
    Nach einem Jarvis-Update beginnt ein frisches Gespräch (alte Gedanken-Blöcke passen sonst nicht)."""
    messages, updated = store.load_chat(conn, phone)
    key = f"chatfp:{store.digits(phone) or phone}"
    same = store.get_state(conn, key) == _fingerprint(system)
    if not same or not updated or datetime.fromisoformat(updated) < datetime.now() - timedelta(hours=max_age_h) \
            or len(messages) > 80:
        store.set_state(conn, key, _fingerprint(system))
        return []  # neues Gespräch beginnen (alte Verläufe werden nie umgeschrieben)
    return messages


def _is_binding_error(exc: Exception) -> bool:
    return isinstance(exc, anthropic.BadRequestError) and "thinking" in str(exc) and "signature" in str(exc)


# --------------------------------------------------------------------------- Owner
OWNER_SYSTEM = f"""Du bist Jarvis, der autonome Recruiting-Assistent von {config.RECRUITER_NAME}
({config.AGENCY_NAME}). Du vermittelst Gesundheitspersonal in die Schweiz und arbeitest selbstständig.

{config.REQUIREMENTS_TEXT}

Tagesziel: mindestens {config.DAILY_TARGET} vermittelbare Kandidaten (Tier A/B).
Bewerbungsformular für Kandidaten: {config.PUBLIC_URL}/bewerbung
Telefonnummer für Kandidaten und Kliniken (Jarvis nimmt ab): {config.CALL_IN_NUMBER or "noch nicht eingerichtet"}
In Inseraten immer Formular-Link UND Telefonnummer nennen („Jetzt anrufen oder in 2 Minuten bewerben“).

DEIN AUTOPILOT LÄUFT AUTOMATISCH AUF DEM SERVER (du musst nichts einrichten und nichts empfehlen):
- Jeden Morgen um {config.MORNING_HOUR} Uhr: grosse Suche in allen Bereichen, bei Bedarf Zusatzrunden in weiteren Regionen.
- Tagsüber ({config.SEARCH_HOURS[0]}–{config.SEARCH_HOURS[1]} Uhr): alle {config.SEARCH_EVERY_HOURS} Stunden eine Suchrunde mit wechselnden Bereichen/Regionen.
- Neue Bewerbungen (Formular, WhatsApp, E-Mail) werden sofort geprüft; jede Nacht um 3 Uhr Selbst-Update.
- Täglich um 10 und 18 Uhr: neues Inserat – automatisch auf der Facebook-Seite (wenn verbunden) und als
  fertiger Text für Facebook-Gruppen in den Meldungen. In Gruppen/Kleinanzeigen darf nicht automatisch
  gepostet werden (Kontosperre) – dort postet Cemal-Can den Text selbst.
Behaupte nie, du könntest dich nicht zeitlich wiederholen oder brauchst einen cron-Job – das läuft bereits.

Du wirst per WhatsApp, App oder Siri gesteuert. Regeln:
- AUSFÜHREN STATT FRAGEN: Jeder Befehl von Cemal-Can wird sofort und vollständig mit deinen Werkzeugen erledigt,
  auch wenn er mehrere Schritte braucht (z.B. suchen → bewerten → zuordnen → vorstellen). Stelle KEINE Rückfragen.
  Ist etwas mehrdeutig, wähle die sinnvollste Auslegung, führe sie aus und nenne die Annahme in einem Satz.
  Fehlen Angaben (z.B. eine E-Mail), erledige alles andere trotzdem und melde am Ende kurz, was noch fehlt.
- Antworte mit dem ERGEBNIS: was du erledigt hast, mit Namen und Zahlen. Keine Ankündigungen wie „ich werde…".
- Antworte kurz und WhatsApp-tauglich: keine Tabellen, kein Markdown ausser *fett*, maximal ca. 15 Zeilen.
- Nenne Kandidaten immer mit Name, Bereich, Tier und ID.
- Arbeite wie der beste Personalvermittler: Interessierte Kandidaten sofort passenden Firmen zuordnen
  (passende_firmen) und direkt anonym vorstellen (kandidat_vorstellen). Wer nicht
  antwortet, wird nachgefasst. Ein Kandidat ist erst vermittelt, wenn ein Vertrag unterschrieben ist.
- GESCHÄFTSMODELL: Hansa Personal findet und qualifiziert Kandidaten und liefert sie an Schweizer
  Partner-Personalvermittler (mit kantonaler und SECO-Bewilligung). Die Partner vermitteln an die Arbeitgeber.
  Hansa schliesst KEINE Vermittlungsverträge mit Arbeitgebern ab. Rufen Arbeitgeber an oder melden Bedarf,
  nimm die Anfrage auf und leite sie als Lead an Cemal-Can / den Partner weiter. Kandidaten zahlen nie etwas.
- 'Kunden' (Status 'kunde') sind die Partner-Vermittler. Sie haben Vorrang: Sie werden automatisch beliefert, sobald ein passender
  Kandidat Interesse bestätigt. Fehlt einem Kunden die E-Mail, lege ihn trotzdem an und erwähne es im Ergebnis. Wenn Cemal-Can eine Liste von
  Arbeitgebern schickt, lege jeden mit kunde_anlegen an.
- Preise: Nenne nur Honorare, die mit preis_setzen hinterlegt sind. Erfinde nie Preise oder Rabatte.
- Kandidaten-IDs dürfen abgekürzt werden (die ersten 6 Zeichen reichen).
- Wenn das Tagesziel nicht erreicht ist, schlage konkrete Schritte vor (z.B. Web-Suche mit weiterem Fokus,
  Stelleninserat mit Formular-Link posten) – du kannst Inseratstexte selbst schreiben.
- Rechtliche Leitplanken sind im Code fest eingebaut (Einwilligung, Sperrliste, Anrufzeiten).
  Versuche nie, sie zu umgehen, und erkläre sie kurz, wenn ein Auftrag daran scheitert."""


_owner_lock = threading.Lock()


def handle_owner(text: str) -> str:
    """Ein Befehl von dir (WhatsApp, iPhone-App oder Siri). Alle teilen sich einen Verlauf."""
    with _owner_lock:
        return _handle_owner(text)


def _handle_owner(text: str) -> str:
    conn = store.connect()
    phone = config.OWNER_WHATSAPP or "app"
    messages = _conversation(conn, phone, max_age_h=3, system=OWNER_SYSTEM)
    messages.append({"role": "user", "content": f"[{datetime.now():%d.%m.%Y %H:%M}] {text}"})
    reply = ""
    for _ in range(25):
        kwargs = dict(model=config.MODEL, max_tokens=16000, system=OWNER_SYSTEM, tools=TOOL_DEFS,
                      output_config={"effort": "low" if config.SPARMODUS else "medium"})
        try:
            response = brain.create(**kwargs, messages=messages)
        except anthropic.BadRequestError as exc:
            if not _is_binding_error(exc) or len(messages) <= 1:
                raise
            # Selbstheilung: alter Verlauf passt nicht mehr → nur mit dem aktuellen Auftrag neu beginnen
            log.warning("Verlauf zurückgesetzt: %s", exc)
            messages = [messages[-1]] if messages[-1]["role"] == "user" and isinstance(
                messages[-1]["content"], str) else [{"role": "user", "content": f"[{datetime.now():%d.%m.%Y %H:%M}] {text}"}]
            response = brain.create(**kwargs, messages=messages)
        messages.append({"role": "assistant", "content": _dump(response.content)})
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out, err = run_tool(block.name, block.input or {})
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": out, "is_error": err})
            messages.append({"role": "user", "content": results})
            continue
        reply = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "refusal":
            reply = reply or "Das kann ich so nicht ausführen."
        break
    else:
        reply = reply or "Ich habe viele Schritte gebraucht und abgebrochen. Bitte Auftrag präzisieren."
    store.save_chat(conn, phone, messages)
    return reply or "Erledigt."


# --------------------------------------------------------------------------- Kandidaten
STOP_WORDS = re.compile(r"^\s*(stop|stopp|abmelden|kein interesse|nicht mehr kontaktieren)\b", re.I)

CANDIDATE_SYSTEM = f"""Du bist Jarvis, der KI-Assistent der Personalvermittlung {config.AGENCY_NAME}
(Ansprechperson: {config.RECRUITER_NAME}). Du chattest per WhatsApp mit Gesundheitsfachpersonen.

{config.REQUIREMENTS_TEXT}

Regeln:
- In deiner ersten Nachricht eines Gesprächs sagst du kurz, dass du ein KI-Assistent bist.
- Kurze, freundliche Nachrichten in Sie-Form, maximal 3-4 Sätze, eine Frage pro Nachricht.
- Ziel: Interesse klären, fehlende Angaben erfragen (Diplom, Deutsch-Zertifikat, SRK/MEBEKO-Stand,
  Verfügbarkeit, Wunschregion, Pensum) und um den Lebenslauf als PDF bitten.
  Wenn noch kein Profil vorliegt, auf das Formular verweisen: {config.PUBLIC_URL}/bewerbung
  Wer lieber telefoniert, kann jederzeit anrufen: {config.CALL_IN_NUMBER or config.PUBLIC_URL}
- Bei Interesse: Telefontermin mit {config.RECRUITER_NAME} vorschlagen.
- Versprich keine konkrete Stelle, keinen Lohn und keine Anerkennung.
- Schreibe am Ende deiner Antwort auf einer eigenen Zeile Steuer-Tags, wenn zutreffend:
  [STATUS:interessiert] oder [STATUS:kein_interesse]
  [OWNER: kurze Info an den Recruiter] (z.B. bei Terminwunsch oder wichtigen Fragen)
  Diese Tags sieht die Person nicht."""

TAG_RE = re.compile(r"\[(STATUS|OWNER):\s*([^\]]+)\]")


def _download_media(ref: str) -> bytes:
    """ref = 'meta:<media-id>' (Meta Cloud API) oder eine Twilio-Media-URL."""
    if ref.startswith("meta:"):
        return messaging.meta_download(ref[5:])[0]
    r = requests.get(ref, auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
                     allow_redirects=True, timeout=60)
    r.raise_for_status()
    return r.content


TAKEOVER_HOURS = 24


def owner_took_over(conn, phone: str) -> bool:
    """Du hast diesem Kontakt in den letzten 24h selbst geschrieben → Jarvis antwortet nicht dazwischen."""
    ts = store.get_state(conn, f"takeover:{store.digits(phone)[-9:]}")
    return bool(ts) and datetime.fromisoformat(ts) > datetime.now() - timedelta(hours=TAKEOVER_HOURS)


def handle_candidate(sender: str, text: str, media: list[tuple[str, str]]) -> str | None:
    conn = store.connect()
    if owner_took_over(conn, sender):
        row = store.find_candidate_by_phone(conn, sender)
        who = row["name"] if row else f"+{store.digits(sender)}"
        store.add_notification(conn, f"💬 {who} (du chattest selbst): {text[:300]}")
        return None
    if STOP_WORDS.match(text or ""):
        store.add_optout(conn, sender)
        row = store.find_candidate_by_phone(conn, sender)
        if row:
            store.set_status(conn, row["key"], "kein_interesse", "per WhatsApp abgemeldet")
        return "Alles klar, wir kontaktieren Sie nicht mehr. Alles Gute!"

    # Lebenslauf per WhatsApp geschickt → sofort prüfen
    extra = ""
    for url, ctype in media:
        ext = {"application/pdf": ".pdf",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
               "text/plain": ".txt"}.get(ctype)
        if not ext:
            continue
        try:
            cv = sources.file_to_text("cv" + ext, _download_media(url))
            if cv:
                raw = sources.RawProfile(source=f"WhatsApp: +{store.digits(sender)}",
                                         text=f"Telefon (WhatsApp): +{store.digits(sender)}\n\n{cv}",
                                         consent_whatsapp=True)
                c = pipeline.evaluate(raw)
                store.upsert(conn, c)
                extra += (f"\n(System: Lebenslauf erhalten und geprüft: Tier {c.tier}, Score {c.score}. "
                          f"Fehlt noch: {'; '.join(c.missing) or 'nichts'})")
                if c.tier in ("A", "B"):
                    messaging.notify_owner(f"📄 Neuer Lebenslauf per WhatsApp: {c.assessment.full_name} – "
                                           f"{_role(c)}, Tier {c.tier} ({c.score}). ID {store.candidate_key(c)}")
        except Exception as exc:  # noqa: BLE001
            log.error("Lebenslauf aus WhatsApp nicht lesbar: %s", exc)
            extra += "\n(System: Anhang konnte nicht gelesen werden.)"

    row = store.find_candidate_by_phone(conn, sender)
    profile = "Noch kein Profil vorhanden."
    if row:
        store.grant_whatsapp_consent(conn, row["key"])
        c = store.load(row)
        profile = (f"Bekanntes Profil: {c.assessment.full_name}, {_role(c)}, Deutsch {c.assessment.german_level}, "
                   f"Anerkennung {c.assessment.recognition_status}, Tier {c.tier}, Status {row['status']}. "
                   f"Fehlt noch: {'; '.join(c.missing) or 'nichts'}")

    messages = _conversation(conn, sender, max_age_h=24, system=CANDIDATE_SYSTEM)
    messages.append({"role": "user", "content": f"(System-Info, für die Person unsichtbar: {profile})\n\n"
                                                f"{text or '(Anhang)'}{extra}"})
    try:
        response = brain.create(
            model=config.MODEL, max_tokens=4000,
            system=CANDIDATE_SYSTEM, output_config={"effort": "low"},
            messages=messages,
        )
    except anthropic.APIError as exc:
        log.error("Kandidaten-Chat fehlgeschlagen: %s", exc)
        return None
    messages.append({"role": "assistant", "content": _dump(response.content)})
    store.save_chat(conn, sender, messages)

    reply = "".join(b.text for b in response.content if b.type == "text")
    for kind, value in TAG_RE.findall(reply):
        value = value.strip()
        if kind == "STATUS" and row and value in store.STATUSES:
            store.set_status(conn, row["key"], value, "WhatsApp-Chat")
            if value == "interessiert":
                messaging.notify_owner(f"🔥 {row['name']} ist interessiert (WhatsApp). ID {row['key'][:6]}")
                matching.auto_deliver()
        elif kind == "OWNER":
            who = row["name"] if row else f"+{store.digits(sender)}"
            messaging.notify_owner(f"💬 {who}: {value}")
    return TAG_RE.sub("", reply).strip() or None
