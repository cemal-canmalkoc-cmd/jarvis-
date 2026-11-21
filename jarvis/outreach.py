"""Headhunter-Ansprache: Jarvis schreibt gefundene Kandidaten selbst an und lädt sie ein,
sich per WhatsApp bei Cemal-Can zu melden (oder sich im Formular zu bewerben).

Regeln (fest eingebaut):
- Nur Personen, die selbst öffentlich ein Stellengesuch mit E-Mail-Adresse veröffentlicht haben.
- Jede Adresse höchstens EINMAL, mit Abmelde-Hinweis; Sperrliste wird beachtet.
- Nur passende Profile (nicht Tier X).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from . import config, store
from .models import ScoredCandidate
from .whatsapp import role_phrase

log = logging.getLogger("jarvis.outreach")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def contact_number() -> str:
    return config.CONTACT_WHATSAPP or config.JARVIS_WHATSAPP_NUMBER


def readable_number(national: bool = True) -> str:
    """Deine WhatsApp-Nummer als Klartext, z. B. '0176 …' (Deutschland) oder '+49 176 …' (Schweiz)."""
    d = "".join(ch for ch in contact_number() if ch.isdigit())
    if not d:
        return ""
    if d.startswith("49") and len(d) > 6:
        return (f"0{d[2:5]} {d[5:]}" if national else f"+49 {d[2:5]} {d[5:]}")
    return "+" + d


def wa_link(text: str = "") -> str:
    num = "".join(ch for ch in contact_number() if ch.isdigit())
    return f"https://wa.me/{num}" + (f"?text={quote(text)}" if text else "")


WA_TEXTS = {
    "lkw": "Hallo Hansa Personal, ich bin LKW-Fahrer und suche einen neuen Job.\nFührerschein (C/CE): \n"
           "Modul 95 / Fahrerkarte: \nWohnort (PLZ): \nAb wann: \n(Lebenslauf/Führerschein schicke ich als Foto mit)",
    "pflege": "Hallo Hansa Personal, ich interessiere mich für eine Stelle in der Schweiz.\nBeruf: \n"
              "Deutschniveau: \nSRK-Anerkennung (ja/nein/läuft): \nWohnort: \n(Lebenslauf schicke ich als PDF/Foto mit)",
    "arzt": "Hallo Hansa Personal, ich interessiere mich als Ärztin/Arzt für eine Stelle in der Schweiz.\n"
            "Fachrichtung: \nDeutschniveau: \nMEBEKO (ja/nein/läuft): \n(Lebenslauf schicke ich mit)",
    "firma": "Hallo Hansa Personal, wir suchen Personal.\nFirma: \nOrt: \nGesucht (z.B. CE-Fahrer, Pflegefachkraft): \nAnzahl: ",
}


def wa_short(bereich: str = "lkw", quelle: str = "") -> str:
    """Kurzer, zählbarer Link, der direkt in deinen WhatsApp-Chat führt (mit vorausgefülltem Text)."""
    return f"{config.PUBLIC_URL}/wa?b={bereich}" + (f"&q={quelle}" if quelle else "")


def can_email() -> bool:
    from .matching import mail_ready
    return mail_ready() or config.OUTBOX


def build_email(c: ScoredCandidate) -> tuple[str, str]:
    a = c.assessment
    first = a.full_name.split()[0] if a.full_name and a.full_name.lower() not in ("unbekannt", "") else ""
    greeting = f"Guten Tag {first}" if first else "Guten Tag"
    role = role_phrase(a)
    lkw = a.category == "lkw"
    hello = (f"Hallo, ich habe Ihr Stellengesuch gesehen ({role}). Gerne mehr Infos zu den Fahrerstellen."
             if lkw else f"Hallo, ich habe Ihr Stellengesuch gesehen ({role}). Gerne mehr Infos zur Schweiz.")
    rec = ("Ihre SRK-Anerkennung" if a.category == "pflege" else "Ihr MEBEKO-Stand") \
        if a.recognition_status in ("anerkannt", "positiver_precheck") else None
    subject = (f"Ihr Stellengesuch als {role} – passende Fahrerstellen" if lkw
               else f"Ihr Stellengesuch als {role} – Stellen in der Schweiz")
    offer = ("wir vermitteln LKW-Fahrer/innen an Speditionen und Logistikunternehmen in ganz Deutschland\n"
             "(Nah- und Fernverkehr). Für Sie ist das komplett kostenlos." if lkw else
             "wir vermitteln Pflegefachpersonen und Ärztinnen/Ärzte an Spitäler, Kliniken\n"
             "und Heime in der Schweiz. Für Sie ist das komplett kostenlos.")
    body = f"""{greeting}

ich bin auf Ihr Stellengesuch als {role} aufmerksam geworden. Ich bin {config.RECRUITER_NAME} von
{config.AGENCY_NAME} – {offer}
{f"{rec} ist dabei ein grosser Vorteil." if rec else ""}
Wenn Sie Interesse haben, schreiben Sie mir einfach per WhatsApp (Lebenslauf gern als Foto mitschicken):
{wa_short('lkw' if lkw else ('arzt' if a.category == 'arzt' else 'pflege'), 'mail')}

Oder bewerben Sie sich in 2 Minuten online: {config.PUBLIC_URL}/bewerbung

Freundliche Grüsse
{config.RECRUITER_NAME}
{config.AGENCY_NAME}

Sie möchten keine weiteren Nachrichten? Antworten Sie einfach mit „STOP" – wir melden uns dann nicht mehr."""
    return subject, body.replace("\n\n\n", "\n\n")


def reach_out(c: ScoredCandidate) -> str:
    """Einmalige E-Mail an einen gefundenen Kandidaten. Gibt einen Status zurück."""
    email = (c.assessment.email or "").strip()
    if c.tier == "X":
        return "ungeeignet"
    if not EMAIL_RE.match(email):
        return "keine_email"
    conn = store.connect()
    key = f"mailed:{email.lower()}"
    if (store.get_state(conn, key) or store.is_opted_out(conn, c.assessment.phone)
            or store.get_state(conn, f"optout_mail:{email.lower()}")):
        return "schon_kontaktiert"
    if not can_email():
        return "email_nicht_eingerichtet"
    from .matching import send_email
    subject, body = build_email(c)
    send_email(email, subject, body)
    store.set_state(conn, key, "1")
    store.set_status(conn, store.candidate_key(c), "kontaktiert", f"E-Mail an {email} (Antworten bearbeitet Jarvis)")
    if not store.get_convo(conn, f"mail:{email.lower()}"):
        store.save_convo(conn, f"mail:{email.lower()}", "kandidat",
                         [{"role": "user", "content": "(Jarvis hat die Person per E-Mail angeschrieben)"},
                          {"role": "assistant", "content": body}], store.candidate_key(c))
    return "gesendet"



def portal_message(c: ScoredCandidate) -> str:
    """Kurze Nachricht zum Einfügen im Portal (kleinanzeigen, quoka, anibis …)."""
    role = role_phrase(c.assessment)
    if c.assessment.category == "lkw":
        return (f"Hallo, ich habe Ihr Stellengesuch als {role} gesehen. Ich bin {config.RECRUITER_NAME} von "
                f"{config.AGENCY_NAME} – wir vermitteln Fahrer kostenlos an Speditionen in ganz Deutschland "
                f"(Nah- und Fernverkehr). Interesse? Schreiben Sie mir einfach per WhatsApp"
                + (f" an {readable_number()}" if readable_number() else "")
                + f" (Lebenslauf oder Führerschein gern als Foto mitschicken): {wa_short('lkw', 'portal')} "
                f"– oder online bewerben: {config.PUBLIC_URL}/bewerbung?bereich=lkw")
    arzt = c.assessment.category == "arzt"
    who = "Ärztinnen und Ärzte" if arzt else "Pflegefachkräfte"
    help_ = "wir begleiten das MEBEKO-Verfahren" if arzt else "wir helfen bei der SRK-Anerkennung"
    return (f"Hallo, ich habe Ihr Stellengesuch als {role} gesehen. Ich bin {config.RECRUITER_NAME} von "
            f"{config.AGENCY_NAME} – wir vermitteln {who} kostenlos an Kliniken in der Schweiz ({help_}). "
            f"Interesse? Schreiben Sie mir gern per WhatsApp"
            + (f" an {readable_number(national=False)}" if readable_number() else "")
            + f" (Lebenslauf als PDF/Foto genügt): {wa_short('arzt' if arzt else 'pflege', 'portal')} "
            f"– oder online: {config.PUBLIC_URL}/bewerbung")


def portal_digest(cands: list[ScoredCandidate]) -> str | None:
    """Eine Meldung mit allen neuen Gesuchen, die nur über das Portal erreichbar sind."""
    rows = [c for c in cands if c.tier != "X"]
    if not rows:
        return None
    with_phone = [c for c in rows if c.whatsapp_link]
    lines = [f"📋 {len(rows)} neue Stellengesuche gefunden.", ""]
    if with_phone:
        lines.append("📱 Mit Nummer in der Anzeige – 1× tippen, Nachricht ist fertig, nur noch senden:")
        for c in with_phone[:10]:
            lines.append(f"• {role_phrase(c.assessment)}, {c.assessment.current_location or '?'}: {c.whatsapp_link}")
        lines.append("")
    lines.append("💬 Nur übers Portal erreichbar (Anzeige öffnen → Nachricht einfügen):")
    for c in [c for c in rows if not c.whatsapp_link][:10]:
        a = c.assessment
        lines.append(f"• {role_phrase(a)}, {a.current_location or '?'} – Tier {c.tier}\n  {c.source}")
    lines += ["", "Nachricht zum Kopieren:", portal_message(rows[0])]
    return "\n".join(lines)
