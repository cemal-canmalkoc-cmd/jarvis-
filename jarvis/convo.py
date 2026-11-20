"""KI-Gespräche ohne dich: Jarvis chattet mit Bewerbern (Web-Chat + E-Mail) und antwortet Firmen.

Ablauf Bewerber:  Fragen klären → Einwilligung holen → Profil speichern (Status „interessiert")
                  → Unterlagen-Link schicken → automatisch an passende Firmen vorstellen.
Ablauf Firma:     Antwort lesen → Absicht erkennen (will Unterlagen/Gespräch, kein Bedarf, Frage,
                  eingestellt) → passend handeln und antworten.

Kosten: nur innerhalb des Gesprächsbudgets (CHAT_MAX_USD pro Tag) und solange die
5-Tage-Freigabe läuft. Danach antwortet Jarvis höflich ohne KI und fragt dich nach „Weiter".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from . import brain, budget, config, messaging, store

log = logging.getLogger("jarvis.convo")

STOP_RE = re.compile(r"^\s*(stop|stopp|abmelden|kein interesse|nicht mehr kontaktieren)\b", re.I)

CANDIDATE_SYSTEM = f"""Du bist Jarvis, der KI-Assistent der Personalvermittlung {config.AGENCY_NAME}
(Inhaber: {config.RECRUITER_NAME}). Du sprichst mit Menschen, die eine Stelle suchen.

Bereiche:
1) Gesundheit Schweiz: {config.REQUIREMENTS_TEXT}
2) LKW-Fahrer Deutschland: {config.LKW_REQUIREMENTS_TEXT}

Deine Aufgabe: Bewerber freundlich und schnell qualifizieren, damit {config.AGENCY_NAME} sie Arbeitgebern
vorstellen kann. Erfrage nacheinander (eine Frage pro Nachricht, nur was noch fehlt):
- Name, Beruf/Bereich
- Pflege: Diplom/Examen (Land), Fachgebiet, Deutsch-Niveau, SRK-Anerkennung? Ärzte: Fachrichtung, MEBEKO?
  LKW: Führerscheinklasse (C/CE), Fahrerkarte, Modul 95 (Schlüsselzahl 95), ADR, Nah-/Fernverkehr, Erfahrung
- Wohnort/PLZ, ab wann verfügbar
- Telefonnummer und E-Mail
- Zum Schluss die Einwilligung: „Dürfen wir Ihr Profil anonym passenden Arbeitgebern vorstellen und Ihre
  Unterlagen weitergeben, wenn ein Arbeitgeber Interesse hat?"

Regeln:
- In deiner ersten Nachricht sagst du kurz, dass du ein KI-Assistent bist.
- Kurz, warm, klar: höchstens 3 Sätze. Pflege/Ärzte in Sie-Form, LKW-Fahrer gern per Du, wenn sie duzen.
- Für Bewerber ist alles kostenlos. Versprich keine konkrete Stelle, keinen Lohn, keine Anerkennung.
- Wer kein Interesse hat oder „STOP" schreibt: freundlich verabschieden, status = kein_interesse.
- Bei Fragen, die du nicht sicher beantworten kannst: sagen, dass sich {config.RECRUITER_NAME} meldet.

Antworte als JSON:
- antwort: deine Nachricht an die Person
- status: "offen" | "interessiert" (will vermittelt werden) | "kein_interesse"
- einwilligung: true nur, wenn die Person der Vorstellung/Weitergabe ausdrücklich zugestimmt hat
- profil: ALLE bisher bekannten Angaben als kurzer Text (Name, Telefon, E-Mail, Beruf, Qualifikationen,
  Sprache, Ort, Verfügbarkeit …) – kumulativ, nichts erfinden
- fertig: true, wenn Name, Beruf/Qualifikation, Ort, ein Kontaktweg UND die Einwilligung vorliegen"""

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "antwort": {"type": "string"},
        "status": {"type": "string", "enum": ["offen", "interessiert", "kein_interesse"]},
        "einwilligung": {"type": "boolean"},
        "profil": {"type": "string"},
        "fertig": {"type": "boolean"},
    },
    "required": ["antwort", "status", "einwilligung", "profil", "fertig"],
    "additionalProperties": False,
}

COMPANY_SYSTEM = f"""Du bist Jarvis, KI-Assistent der Personalvermittlung {config.AGENCY_NAME}
(Inhaber: {config.RECRUITER_NAME}). Du beantwortest E-Mails von Arbeitgebern, denen wir anonyme
Kandidatenprofile geschickt haben.

Konditionen: Honorar nur bei Einstellung, keine Vorabkosten, keine Garantie/Nachbesetzung.
Preise (falls gefragt): {{preise}}
Du unterschreibst nie Verträge und sagst keine Sonderkonditionen zu – bei Verhandlungswünschen
meldet sich {config.RECRUITER_NAME} persönlich (absicht = frage, an_inhaber ausfüllen).

Erkenne die Absicht der Firma:
- "unterlagen": möchte den Kandidaten kennenlernen / Unterlagen / Gespräch / Kontakt
- "eingestellt": Kandidat wurde eingestellt bzw. Vertrag/Start steht (startdatum JJJJ-MM-TT, wenn genannt)
- "absage": kein Interesse/kein Bedarf/Kandidat passt nicht
- "keine_werbung": will keine weiteren Vorschläge
- "frage": sonstige Frage
Antworte als JSON: absicht, antwort (kurze, professionelle E-Mail-Antwort in Sie-Form, ohne Betreff,
mit Gruss „{config.RECRUITER_NAME}, {config.AGENCY_NAME}"), startdatum (oder ""), an_inhaber (kurze Info an
den Inhaber, wenn er persönlich etwas tun muss, sonst "")."""

COMPANY_SCHEMA = {
    "type": "object",
    "properties": {
        "absicht": {"type": "string", "enum": ["unterlagen", "eingestellt", "absage", "keine_werbung", "frage"]},
        "antwort": {"type": "string"},
        "startdatum": {"type": "string"},
        "an_inhaber": {"type": "string"},
    },
    "required": ["absicht", "antwort", "startdatum", "an_inhaber"],
    "additionalProperties": False,
}

EST_REPLY_USD = 0.002
OFFLINE_REPLY = ("Vielen Dank für Ihre Nachricht! Sie ist bei uns angekommen – wir melden uns so schnell wie "
                 "möglich bei Ihnen.")


def _ask(system: str, schema: dict, messages: list) -> dict | None:
    """Ein KI-Aufruf im Gesprächsbudget. None = Budget/Freigabe fehlt oder Fehler."""
    if not budget.chat_allowed(EST_REPLY_USD):
        budget.remind_autonomy()
        return None
    try:
        resp = brain.create(model=config.MODEL, max_tokens=1500, system=system,
                            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                            messages=messages)
        budget.add_chat_spend(budget.cost_of(config.MODEL, getattr(resp, "usage", None)))
        text = "".join(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        log.error("KI-Gespräch fehlgeschlagen: %s", exc)
        return None


# --------------------------------------------------------------------------- Bewerber
def candidate_turn(convo_id: str, text: str, channel: str, contact: str = "") -> str:
    """Eine Nachricht eines Bewerbers verarbeiten und die Antwort zurückgeben.
    convo_id: z. B. 'web:<id>' oder 'mail:<adresse>'; contact: E-Mail/Telefon, falls bekannt."""
    conn = store.connect()
    conv = store.get_convo(conn, convo_id) or {"messages": [], "cand_key": None}
    msgs = conv["messages"]
    if STOP_RE.match(text or ""):
        if conv["cand_key"]:
            store.set_status(conn, conv["cand_key"], "kein_interesse", f"per {channel} abgemeldet")
        if "@" in contact:
            store.set_state(conn, f"optout_mail:{contact.lower()}", date.today().isoformat())
        store.save_convo(conn, convo_id, "kandidat", msgs + [{"role": "user", "content": text},
                                                              {"role": "assistant", "content": "STOP"}],
                         conv["cand_key"])
        return "Alles klar, wir kontaktieren Sie nicht mehr. Alles Gute!"
    hint = f"(Kanal: {channel}{', Kontakt: ' + contact if contact else ''})"
    msgs = msgs[-30:] + [{"role": "user", "content": f"{hint}\n{text}" if not msgs else text}]
    out = _ask(CANDIDATE_SYSTEM, CANDIDATE_SCHEMA, msgs)
    if out is None:
        store.save_convo(conn, convo_id, "kandidat", msgs + [{"role": "assistant", "content": OFFLINE_REPLY}],
                         conv["cand_key"])
        store.add_notification(conn, f"💬 Bewerber-Nachricht ({channel}, ohne KI beantwortet): {text[:300]}")
        return OFFLINE_REPLY
    reply = out["antwort"].strip()
    cand_key = conv["cand_key"]
    if out["status"] == "kein_interesse" and cand_key:
        store.set_status(conn, cand_key, "kein_interesse", f"{channel}-Gespräch")
    ready = out["fertig"] and out["einwilligung"] and out["status"] != "kein_interesse"
    if ready and not store.get_state(conn, f"convo_done:{convo_id}"):
        if cand_key:
            row = store.get_candidate(conn, cand_key)
            if row and row["status"] in ("neu", "kontaktiert"):
                store.set_status(conn, cand_key, "interessiert", f"Einwilligung im {channel}-Gespräch")
                from . import matching
                matching.auto_deliver()
                messaging.notify_owner(f"🔥 {row['name']} ist interessiert ({channel}) – Jarvis kümmert sich. "
                                       f"Du musst nichts tun.")
        else:
            cand_key = _create_candidate(out["profil"], channel, contact)
        if cand_key:
            from . import deals
            store.set_state(conn, f"convo_done:{convo_id}", date.today().isoformat())
            reply += ("\n\nDamit wir Sie direkt vorstellen können, laden Sie bitte hier Ihren Lebenslauf und Ihre "
                      f"Zeugnisse hoch: {deals.upload_link(cand_key)}")
    msgs.append({"role": "assistant", "content": reply})
    store.save_convo(conn, convo_id, "kandidat", msgs, cand_key)
    return reply


def _create_candidate(profile: str, channel: str, contact: str) -> str | None:
    """Fertiges Gespräch → Profil bewerten, als interessiert speichern, automatisch vorstellen."""
    from . import deals, matching, pipeline, sources
    from .whatsapp import role_phrase
    conn = store.connect()
    raw = sources.RawProfile(source=f"KI-Gespräch ({channel})",
                             text=f"ANGABEN AUS DEM BEWERBER-GESPRÄCH (Person hat zugestimmt)\n"
                                  f"{('Kontakt: ' + contact) if contact else ''}\n{profile}",
                             consent_whatsapp=True, consent_call=True)
    try:
        c = pipeline.evaluate(raw)
    except Exception as exc:  # noqa: BLE001
        log.error("Gesprächsprofil nicht auswertbar: %s", exc)
        store.add_notification(conn, f"📝 Bewerber aus Gespräch (nicht automatisch auswertbar):\n{profile}")
        return None
    store.upsert(conn, c)
    key = store.candidate_key(c)
    if c.tier == "X":
        store.add_notification(conn, f"📝 Gespräch beendet, passt nicht: {c.assessment.full_name} – {c.assessment.summary}")
        return key
    store.set_status(conn, key, "interessiert", f"KI-Gespräch ({channel}) mit Einwilligung")
    delivered = matching.auto_deliver()
    row = store.get_candidate(conn, key)
    if c.assessment.email and config.SMTP_USER:
        try:
            matching.send_email(c.assessment.email, "Ihre Unterlagen – nächster Schritt", deals.doc_request_text(row))
        except Exception as exc:  # noqa: BLE001
            log.error("Dokument-Mail fehlgeschlagen: %s", exc)
    messaging.notify_owner(f"🤖 Jarvis hat einen Bewerber selbst qualifiziert: {c.assessment.full_name} – "
                           f"{role_phrase(c.assessment)} (Tier {c.tier}). Du musst nichts tun."
                           + (f"\n📦 Schon vorgestellt: {'; '.join(delivered)}" if delivered else ""))
    return key


# --------------------------------------------------------------------------- Firmen
def company_turn(company_id: int, text: str) -> tuple[str | None, str]:
    """E-Mail einer Firma verarbeiten. Gibt (Antworttext oder None, Kurzinfo) zurück."""
    from . import deals, pricing
    conn = store.connect()
    firm = store.get_company(conn, company_id)
    if not firm:
        return None, "Firma unbekannt"
    convo_id = f"firma:{company_id}"
    conv = store.get_convo(conn, convo_id) or {"messages": []}
    cand = _last_presented(conn, company_id)
    context = (f"(Firma: {firm['name']}, {firm['city'] or '?'}; zuletzt vorgestelltes Profil: "
               f"#{cand['key'][:6].upper() if cand else '–'})")
    msgs = conv["messages"][-20:] + [{"role": "user", "content": f"{context}\n\n{text}"}]
    preise = "; ".join(f"{b}: {t}" for b, t in pricing.overview().items())
    out = _ask(COMPANY_SYSTEM.replace("{preise}", preise or "nach Vereinbarung"), COMPANY_SCHEMA, msgs)
    if out is None:
        store.add_notification(conn, f"📧 Antwort von {firm['name']} (bitte selbst lesen – KI-Budget/Freigabe):\n{text[:500]}")
        return None, "ohne KI"
    action = out["absicht"]
    info = f"{firm['name']}: {action}"
    if action == "unterlagen" and cand:
        info = introduce(cand["key"], company_id)
    elif action == "eingestellt" and cand:
        start = out["startdatum"] if re.match(r"^\d{4}-\d{2}-\d{2}$", out["startdatum"] or "") else \
            (date.today() + timedelta(days=30)).isoformat()
        deals.mark_hired(cand["key"], company_id, start)
        info = f"🎉 {firm['name']} hat #{cand['key'][:6].upper()} eingestellt (Start {start})"
    elif action == "absage":
        if cand:
            store.set_status(conn, cand["key"], "interessiert", f"Absage von {firm['name']}")
        store.set_company_status(conn, company_id, firm["status"] if firm["status"] == "kunde" else "angeschrieben",
                                 "Absage zum Profil")
    elif action == "keine_werbung":
        store.set_company_status(conn, company_id, "nicht_anrufen", "möchte keine Vorschläge (per E-Mail)")
    if out["an_inhaber"]:
        messaging.notify_owner(f"📧 {firm['name']}: {out['an_inhaber']}")
    reply = out["antwort"].strip()
    msgs.append({"role": "assistant", "content": reply})
    store.save_convo(conn, convo_id, "firma", msgs, cand["key"] if cand else None, company_id)
    return reply, info


def _last_presented(conn, company_id: int):
    r = conn.execute("SELECT cand_key FROM presentations WHERE company_id=? ORDER BY id DESC LIMIT 1",
                     (company_id,)).fetchone()
    return store.get_candidate(conn, r[0]) if r else None


def introduce(cand_key: str, company_id: int) -> str:
    """Firma will den Kandidaten: Unterlagen schicken und beide direkt miteinander verbinden."""
    from . import deals, matching
    from .whatsapp import role_phrase
    conn = store.connect()
    row = store.get_candidate(conn, cand_key)
    firm = store.get_company(conn, company_id)
    if not row or not firm:
        return "Kandidat oder Firma fehlt."
    a = store.load(row).assessment
    res = deals.send_documents(row["key"], company_id) if firm["email"] else "keine Firmen-E-Mail"
    if a.email:
        try:
            matching.send_email(
                a.email, f"Gute Nachricht: {firm['name']} möchte Sie kennenlernen",
                f"Guten Tag {a.full_name},\n\n{firm['name']} ({firm['city'] or ''}) interessiert sich für Sie als "
                f"{role_phrase(a)}. Wir haben Ihre Unterlagen weitergegeben; das Unternehmen meldet sich direkt bei "
                f"Ihnen, um einen Termin zu vereinbaren.\n"
                + (f"Kontakt: {firm['contact_name'] or ''} {firm['phone'] or ''} {firm['email'] or ''}\n" )
                + f"\nViel Erfolg!\n{config.RECRUITER_NAME}\n{config.AGENCY_NAME}")
        except Exception as exc:  # noqa: BLE001
            log.error("Info an Kandidat fehlgeschlagen: %s", exc)
    deals.mark_interview(row["key"], "wird direkt vereinbart", company_id)
    store.set_state(conn, f"intro_at:{row['key']}", date.today().isoformat())
    store.set_state(conn, f"intro_firm:{row['key']}", str(company_id))
    if firm["status"] in ("neu", "angeschrieben", "angerufen"):
        store.set_company_status(conn, company_id, "interessiert", f"will #{row['key'][:6].upper()} kennenlernen")
    messaging.notify_owner(f"🤝 {firm['name']} will {a.full_name} kennenlernen – Unterlagen sind raus, beide "
                           f"sind verbunden. ({res}) Du musst nichts tun.")
    return f"🤝 {a.full_name} ↔ {firm['name']} verbunden"


def followups() -> list[str]:
    """7 Tage nach dem Verbinden fragt Jarvis die Firma nach dem Ergebnis (einmal)."""
    from . import matching
    conn = store.connect()
    out = []
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    for row in conn.execute("SELECT * FROM candidates WHERE status='gespraech'").fetchall():
        at = store.get_state(conn, f"intro_at:{row['key']}")
        fid = store.get_state(conn, f"intro_firm:{row['key']}")
        if not at or not fid or at > week_ago or store.get_state(conn, f"intro_followup:{row['key']}"):
            continue
        firm = store.get_company(conn, int(fid))
        if not firm or not firm["email"]:
            continue
        try:
            matching.send_email(firm["email"], f"Kurze Rückfrage zu Profil #{row['key'][:6].upper()}",
                                f"Guten Tag{' ' + firm['contact_name'] if firm['contact_name'] else ''},\n\n"
                                f"wie ist das Kennenlernen mit {row['name']} gelaufen? Eine kurze Antwort genügt – "
                                f"z. B. „eingestellt ab …“ oder „passt leider nicht“.\n\nFreundliche Grüsse\n"
                                f"{config.RECRUITER_NAME}\n{config.AGENCY_NAME}")
            store.set_state(conn, f"intro_followup:{row['key']}", date.today().isoformat())
            out.append(f"{firm['name']} nach Ergebnis gefragt ({row['name']})")
        except Exception as exc:  # noqa: BLE001
            log.error("Nachfrage fehlgeschlagen: %s", exc)
    return out
