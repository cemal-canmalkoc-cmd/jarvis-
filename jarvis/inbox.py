"""Postfach: Jarvis liest neue E-Mails selbst und antwortet.

- Antwort einer Firma → convo.company_turn (Unterlagen schicken, verbinden, Einstellung erfassen …)
- Antwort eines Bewerbers → convo.candidate_turn (Fragen klären, Einwilligung, Unterlagen-Link)
- Unbekannter Absender mit Lebenslauf → als Bewerbung auswerten
- Alles andere (Werbung, Systemmails) bleibt ungelesen liegen.
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
from email.utils import parseaddr

from . import config, matching, sources, store

log = logging.getLogger("jarvis.inbox")

IMAP_BY_SMTP = {
    "smtp-mail.outlook.com": "outlook.office365.com", "mail.gmx.net": "imap.gmx.net", "smtp.web.de": "imap.web.de",
    "smtp.gmail.com": "imap.gmail.com", "securesmtp.t-online.de": "secureimap.t-online.de",
    "smtp.mail.me.com": "imap.mail.me.com", "smtp.mail.yahoo.com": "imap.mail.yahoo.com",
}
SKIP_SENDERS = re.compile(r"(no-?reply|mailer-daemon|postmaster|notification|newsletter|bounce)", re.I)
QUOTE_RE = re.compile(r"\n(Am .{5,80} schrieb|On .{5,80} wrote|-----\s*Original|Von: .+\nGesendet:).*", re.S)


def imap_host() -> str:
    if config.IMAP_HOST:
        return config.IMAP_HOST
    return IMAP_BY_SMTP.get(matching.smtp_host(), "")


def ready() -> bool:
    return bool(config.AUTO_INBOX and matching.mail_ready() and imap_host())


def _body(msg) -> tuple[str, list[tuple[str, bytes]]]:
    text, files = "", []
    for part in msg.walk():
        fname = part.get_filename()
        payload = part.get_payload(decode=True)
        if fname and payload:
            files.append((sources._decode(fname), payload))
        elif part.get_content_type() == "text/plain" and payload and not text:
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    text = QUOTE_RE.sub("", text).strip()
    return text[:4000], files


def handle(sender: str, subject: str, text: str, files: list[tuple[str, bytes]]) -> str | None:
    """Eine E-Mail verarbeiten. Gibt eine Kurzinfo zurück oder None, wenn nicht zuständig."""
    from . import convo, pipeline
    conn = store.connect()
    addr = sender.lower()
    if SKIP_SENDERS.search(addr) or addr == (config.SMTP_USER or "").lower():
        return None
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    firm = store.find_company_by_email(conn, addr)
    if firm:
        reply, info = convo.company_turn(firm["id"], f"Betreff: {subject}\n\n{text}")
        if reply:
            matching.send_email(addr, reply_subject, reply)
        return info
    cand = store.find_candidate_by_email(conn, addr)
    cv_text = ""
    for name, data in files:
        try:
            cv_text += (sources.file_to_text(name, data) or "") + "\n"
        except Exception:  # noqa: BLE001
            pass
    if cand or store.get_convo(conn, f"mail:{addr}"):
        if cand and cv_text.strip():
            path = config.DATA_DIR / "uploads" / f"mail-{cand['key'][:8]}-{files[0][0]}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(files[0][1])
            store.set_state(conn, f"cv:{cand['key']}", str(path))
            text += "\n(System: Lebenslauf als Anhang erhalten.)"
        if store.get_state(conn, f"optout_mail:{addr}"):
            return None
        if cand and not store.get_convo(conn, f"mail:{addr}"):
            store.save_convo(conn, f"mail:{addr}", "kandidat", [], cand["key"])
        reply = convo.candidate_turn(f"mail:{addr}", text, "E-Mail", addr)
        matching.send_email(addr, reply_subject, reply)
        return f"Bewerber {addr} beantwortet"
    looks_like_application = re.search(r"bewerb|lebenslauf|\bcv\b|stelle|job|fahrer|pflege|arzt|ärzt",
                                       f"{subject} {text}", re.I)
    from . import budget
    if cv_text.strip() and looks_like_application and budget.chat_allowed(0.005):  # neue Bewerbung
        raw = sources.RawProfile(source=f"E-Mail: {sender} – {subject}",
                                 text=f"Absender: {sender}\nBetreff: {subject}\n\n{text}\n\n{cv_text}",
                                 consent_call=True)
        c = pipeline.evaluate(raw)
        store.upsert(conn, c)
        key = store.candidate_key(c)
        store.save_convo(conn, f"mail:{addr}", "kandidat", [], key)
        reply = convo.candidate_turn(f"mail:{addr}", f"(Bewerbung per E-Mail mit Lebenslauf)\n{text}", "E-Mail", addr)
        matching.send_email(addr, reply_subject, reply)
        return f"Neue Bewerbung von {addr} (Tier {c.tier})"
    return None


def _login(box) -> None:
    from . import msauth
    if msauth.is_outlook(imap_host()) and msauth.connected():
        token = msauth.xoauth2(config.SMTP_USER)
        box.authenticate("XOAUTH2", lambda _: token.encode())
    else:
        box.login(config.SMTP_USER, config.SMTP_PASSWORD)


def _set_status(ok: bool, err: str = "") -> None:
    from datetime import datetime
    store.set_state(store.connect(), "inbox_status",
                    ("ok:" if ok else "fehler:") + f"{datetime.now():%d.%m. %H:%M}" + (f" {err[:80]}" if err else ""))


def status_text() -> str:
    """Für die App: echtes Ergebnis der letzten Anmeldung am Postfach."""
    if not ready():
        return "Postfach: E-Mail unter ⚙️ eintragen"
    st = store.get_state(store.connect(), "inbox_status") or ""
    if st.startswith("ok:"):
        return f"Postfach ✅ ({st[3:]})"
    if st.startswith("fehler:"):
        return "Postfach ❌ Anmeldung abgelehnt – ⚙️ Testmail für Hilfe"
    return "Postfach: noch nicht geprüft"


def check() -> str:
    """Login am Posteingang testen (für den Testmail-Knopf)."""
    if not config.AUTO_INBOX:
        return "ausgeschaltet (⚙️ AUTO_INBOX)"
    host = imap_host()
    if not host:
        return "Server unbekannt – unter ⚙️ 'Posteingangs-Server' eintragen"
    try:
        box = imaplib.IMAP4_SSL(host, timeout=20)
        _login(box)
        box.select("INBOX")
        _, ids = box.search(None, "UNSEEN")
        box.logout()
        _set_status(True)
        return f"✅ verbunden ({host}), {len(ids[0].split())} ungelesene Mails – Jarvis liest alle 10 Minuten"
    except Exception as exc:  # noqa: BLE001
        _set_status(False, str(exc))
        hint = (" GMX: im GMX-Postfach unter Einstellungen → POP3/IMAP-Abruf den Zugriff erlauben."
                if "gmx" in host else " Prüfe, ob IMAP-Zugriff im Mailkonto erlaubt ist.")
        return f"❌ Anmeldung fehlgeschlagen ({host}): {str(exc)[:120]}.{hint}"


def _rate_ok(sender: str, per_day: int = 6) -> bool:
    """Schutz vor Endlos-Schleifen mit Abwesenheitsnotizen: höchstens X Antworten pro Absender und Tag."""
    from datetime import date
    conn = store.connect()
    key = f"mailreplies:{date.today()}:{sender.lower()}"
    n = int(store.get_state(conn, key) or 0)
    if n >= per_day:
        return False
    store.set_state(conn, key, str(n + 1))
    return True


def poll(max_mails: int = 15) -> list[str]:
    """Neue Mails abholen und beantworten. Nicht zuständige Mails bleiben ungelesen."""
    if not ready():
        return []
    out = []
    try:
        box = imaplib.IMAP4_SSL(imap_host(), timeout=30)
        _login(box)
    except Exception as exc:  # noqa: BLE001
        _set_status(False, str(exc))
        raise
    _set_status(True)
    try:
        box.select("INBOX")
        _, ids = box.search(None, "UNSEEN")
        for mid in ids[0].split()[:max_mails]:
            _, data = box.fetch(mid, "(BODY.PEEK[])")
            msg = email.message_from_bytes(data[0][1])
            sender = parseaddr(sources._decode(msg.get("From")))[1]
            subject = sources._decode(msg.get("Subject"))
            auto = (msg.get("Auto-Submitted", "no").lower() != "no" or msg.get("X-Autoreply")
                    or msg.get("X-Autorespond") or (msg.get("Precedence", "").lower() in ("bulk", "list", "junk")))
            if auto or not _rate_ok(sender):
                continue
            text, files = _body(msg)
            try:
                info = handle(sender, subject, text, files)
            except Exception as exc:  # noqa: BLE001
                log.exception("Mail von %s nicht verarbeitet", sender)
                info = None
                store.add_notification(store.connect(), f"⚠️ Mail von {sender} nicht verarbeitet: {exc}")
            if info:
                box.store(mid, "+FLAGS", "\\Seen")
                out.append(info)
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    return out
