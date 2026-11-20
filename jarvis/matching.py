"""Vermittlung: passende Arbeitgeber finden, Kandidaten anonym vorstellen, nachfassen.

Kandidaten werden nur vorgestellt, wenn sie Interesse bestätigt haben (Status 'interessiert'),
und immer anonym (ohne Name, Telefon, E-Mail). Name erst, wenn die Klinik ein Gespräch möchte
und der Kandidat zustimmt – das macht ihr dann persönlich.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import config, messaging, pricing, store
from .whatsapp import role_phrase

log = logging.getLogger("jarvis.matching")

SYNONYMS = {
    "psychiatrie": ["psychiatr", "psycho"],
    "akutspital": ["akut", "spital", "notfall", "chirurg", "medizin", "station"],
    "geriatrie": ["geriatr", "langzeit", "alters", "pflegeheim", "heim"],
    "langzeitpflege": ["langzeit", "alters", "pflegeheim", "heim"],
    "fage": ["fage", "fachfrau gesundheit", "fachmann gesundheit", "fachperson gesundheit"],
    "anästhesie": ["anästhe", "anaesthe"],
    "innere medizin": ["innere", "allgemeine innere", "aim", "hausarzt"],
    "gynäkologie": ["gynäk", "gynaek", "frauenklinik", "geburt"],
    "radiologie": ["radiolog", "bildgebung"],
    "neurologie": ["neurolog"],
    "rehabilitation": ["reha"],
}


def _keywords(role: str) -> list[str]:
    r = (role or "").lower()
    kws = []
    for key, syn in SYNONYMS.items():
        if key in r or any(s in r for s in syn):
            kws += syn + [key]
    return kws or [w for w in r.replace("(", " ").replace(")", " ").split() if len(w) > 4]


def matches(conn, cand_row, limit: int = 5) -> list[dict]:
    c = store.load(cand_row)
    a = c.assessment
    role = (a.physician_specialty if a.category == "arzt" else a.nursing_field) or ""
    kws = _keywords(role)
    group = ["arzt", "ärzt", "medizin"] if a.category == "arzt" else ["pflege", "fage", "fachperson"]
    out = []
    for f in conn.execute("SELECT * FROM companies WHERE status NOT IN ('kein_bedarf','nicht_anrufen')").fetchall():
        needs = f"{f['needs'] or ''} {f['name']}".lower()
        score = sum(2 for k in kws if k in needs) + sum(1 for g in group if g in needs)
        if a.current_location and f["city"] and f["city"].lower() in a.current_location.lower():
            score += 1
        if f["status"] == "interessiert":
            score += 2
        if f["status"] == "kunde":
            score += 3  # Bestandskunden zuerst beliefern
        if score >= 2:
            out.append({"id": f["id"], "name": f["name"], "ort": f["city"], "bedarf": f["needs"],
                        "status": f["status"], "email": f["email"], "passung": score})
    return sorted(out, key=lambda x: -x["passung"])[:limit]


def anonymous_profile(cand_row) -> str:
    c = store.load(cand_row)
    a = c.assessment
    rec_name = "MEBEKO" if a.category == "arzt" else "SRK"
    rec = {"anerkannt": "liegt vor", "positiver_precheck": "positiver Pre-Check / Zwischenstand",
           "laufend": "Verfahren läuft", "nicht_noetig": "Schweizer Diplom"}.get(a.recognition_status, "in Klärung")
    lines = [
        f"Kandidaten-Nr. {cand_row['key'][:6].upper()}",
        f"Funktion: {role_phrase(a)}",
        f"{rec_name}-Anerkennung: {rec}",
        f"Deutsch: {a.german_level if a.german_level != 'unbekannt' else 'in Klärung'}",
    ]
    if a.years_experience:
        lines.append(f"Berufserfahrung: ca. {a.years_experience:g} Jahre")
    if a.availability:
        lines.append(f"Verfügbar: {a.availability}")
    if a.currently_in_switzerland:
        lines.append("Wohnt bereits in der Schweiz")
    return "\n".join(lines)


SMTP_BY_DOMAIN = {
    "outlook.": "smtp-mail.outlook.com", "hotmail.": "smtp-mail.outlook.com", "live.": "smtp-mail.outlook.com",
    "msn.": "smtp-mail.outlook.com", "gmx.": "mail.gmx.net", "web.de": "smtp.web.de",
    "gmail.": "smtp.gmail.com", "googlemail.": "smtp.gmail.com", "t-online.": "securesmtp.t-online.de",
    "icloud.": "smtp.mail.me.com", "me.com": "smtp.mail.me.com", "yahoo.": "smtp.mail.yahoo.com",
}


def smtp_host() -> str:
    if config.SMTP_HOST:
        return config.SMTP_HOST
    domain = (config.SMTP_USER or "").split("@")[-1].lower()
    return next((h for k, h in SMTP_BY_DOMAIN.items() if domain.startswith(k) or domain == k), "")


def send_email(to: str, subject: str, body: str) -> None:
    host = smtp_host()
    if not (host and config.SMTP_USER and config.SMTP_PASSWORD):
        raise RuntimeError("E-Mail-Versand nicht eingerichtet (E-Mail-Login und Passwort unter ⚙️ Verbindungen)")
    msg = EmailMessage()
    msg["From"] = f"{config.RECRUITER_NAME} – {config.AGENCY_NAME} <{config.SMTP_FROM or config.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, config.SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        hint = (" Outlook/Hotmail: Microsoft lässt das normale Passwort oft nicht mehr zu – erstelle unter "
                "account.microsoft.com → Sicherheit ein App-Kennwort (2-Schritt-Prüfung nötig) und trage das ein."
                if "outlook" in host else " Prüfe Login/Passwort bzw. ob SMTP-Zugriff erlaubt ist.")
        raise RuntimeError(f"Anmeldung beim Mailserver abgelehnt ({host}).{hint}") from exc


def present(cand_key: str, company_id: int) -> str:
    """Stellt einen interessierten Kandidaten einer Klinik anonym per E-Mail vor."""
    conn = store.connect()
    cand = store.get_candidate(conn, cand_key)
    firm = store.get_company(conn, company_id)
    if not cand or not firm:
        return "Kandidat oder Firma nicht gefunden."
    if cand["status"] not in ("interessiert", "vermittelt"):
        return (f"{cand['name']} hat noch kein Interesse bestätigt (Status: {cand['status']}). "
                "Erst nach Zusage vorstellen.")
    if store.was_presented(conn, cand["key"], company_id):
        return f"{cand['name']} wurde {firm['name']} bereits vorgestellt."
    profile = anonymous_profile(cand)
    a = store.load(cand).assessment
    role = (a.physician_specialty if a.category == "arzt" else a.nursing_field)
    if firm["status"] == "kunde":
        terms = "Es gelten die Konditionen unserer Kooperationsvereinbarung."
    else:
        price = pricing.for_candidate(a.category, role)
        terms = (f"Unser Honorar: {price}." if price else
                 "Für Sie entstehen nur bei erfolgreicher Anstellung Kosten; gerne sende ich Ihnen unsere Konditionen.")
    greeting = f"Guten Tag {firm['contact_name']}" if firm["contact_name"] else "Guten Tag"
    body = f"""{greeting}

wie besprochen stelle ich Ihnen eine passende Fachperson vor:

{profile}

Gerne organisiere ich ein Kennenlerngespräch. Den vollständigen Lebenslauf sende ich Ihnen
nach Rücksprache mit der Kandidatin bzw. dem Kandidaten.

{terms}

Freundliche Grüsse
{config.RECRUITER_NAME}
{config.AGENCY_NAME}{chr(10) + "Tel. " + config.CALL_IN_NUMBER if config.CALL_IN_NUMBER else ""}"""
    subject = f"Kandidatenvorschlag: {role_phrase(store.load(cand).assessment)}"
    if not firm["email"]:
        return (f"Für {firm['name']} ist noch keine E-Mail hinterlegt. Text zum Kopieren:\n\n"
                f"Betreff: {subject}\n\n{body}")
    try:
        send_email(firm["email"], subject, body)
    except Exception as exc:  # noqa: BLE001
        return f"E-Mail nicht gesendet ({exc}). Text zum Kopieren:\n\nBetreff: {subject}\n\n{body}"
    store.record_presentation(conn, cand["key"], company_id, "email")
    store.set_company_status(conn, company_id, firm["status"], f"Kandidat {cand['key'][:6].upper()} vorgestellt")
    store.set_status(conn, cand_key, cand["status"], f"Vorgestellt bei {firm['name']}")
    return f"✅ {cand['name']} anonym bei {firm['name']} ({firm['email']}) vorgestellt."


def suggestions(conn, limit: int = 5) -> list[str]:
    """Vermittlungsvorschläge für den Morgenbericht."""
    out = []
    for r in conn.execute("SELECT * FROM candidates WHERE status='interessiert' ORDER BY score DESC LIMIT 20").fetchall():
        m = matches(conn, r, 1)
        if m:
            out.append(f"{r['name']} → {m[0]['name']} ({m[0]['ort'] or '?'}) · "
                       f"„Stell {r['key'][:6]} bei Firma {m[0]['id']} vor\"")
        if len(out) >= limit:
            break
    return out


def auto_deliver(max_per_run: int = 10) -> list[str]:
    """Bestandskunden automatisch beliefern: interessierte Kandidaten an den bestpassenden Kunden
    (mit hinterlegter E-Mail) anonym vorstellen – jeder Kandidat pro Kunde nur einmal."""
    if not config.AUTO_DELIVER:
        return []
    conn = store.connect()
    done = []
    for cand in conn.execute("SELECT * FROM candidates WHERE status='interessiert' ORDER BY score DESC").fetchall():
        for m in matches(conn, cand, 5):
            if m["status"] != "kunde" or not m["email"] or store.was_presented(conn, cand["key"], m["id"]):
                continue
            result = present(cand["key"], m["id"])
            if result.startswith("✅"):
                done.append(result)
                messaging.notify_owner(f"📦 Lieferung: {result}")
            break  # pro Lauf ein Kunde je Kandidat
        if len(done) >= max_per_run:
            break
    return done


def open_customer_needs() -> list[str]:
    """Kundenaufträge, für die noch kein interessierter Kandidat vorgestellt wurde."""
    conn = store.connect()
    out = []
    for k in store.customers(conn):
        n = conn.execute("SELECT COUNT(*) FROM presentations WHERE company_id=?", (k["id"],)).fetchone()[0]
        if k["needs"] and n == 0:
            out.append(f"{k['name']} ({k['city'] or '?'}): {k['needs']}")
    return out
