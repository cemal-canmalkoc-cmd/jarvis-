"""E-Mail lesen (IMAP) und senden (SMTP). Funktioniert z.B. mit einem kostenlosen Gmail-Konto + App-Passwort."""
from __future__ import annotations

import email
import imaplib
import os
import smtplib
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr


@dataclass
class Mail:
    message_id: str
    absender: str          # Antwortadresse (Reply-To bevorzugt, z.B. bei Formspree)
    betreff: str
    text: str


@dataclass
class Gesendet:
    an: str
    betreff: str
    text: str
    cc: list[str] = field(default_factory=list)


def _text_aus(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for teil in msg.walk():
            if teil.get_content_type() == "text/plain" and not teil.get_filename():
                return teil.get_payload(decode=True).decode(teil.get_content_charset() or "utf-8", "replace")
        for teil in msg.walk():  # Fallback: HTML grob entfernen
            if teil.get_content_type() == "text/html":
                import re
                roh = teil.get_payload(decode=True).decode(teil.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", roh)
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


class Postfach:
    def __init__(self) -> None:
        self.user = os.environ["MAIL_USER"]
        self.passwort = os.environ["MAIL_PASS"]
        self.imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")
        self.smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.absender_name = os.environ.get("ABSENDER_NAME", "Vermittlung")

    def neue_mails(self, limit: int = 50) -> list[Mail]:
        mails: list[Mail] = []
        with imaplib.IMAP4_SSL(self.imap_host) as imap:
            imap.login(self.user, self.passwort)
            imap.select("INBOX")
            _, daten = imap.search(None, "UNSEEN")
            for num in daten[0].split()[:limit]:
                _, teile = imap.fetch(num, "(RFC822)")  # markiert als gelesen
                msg = email.message_from_bytes(teile[0][1])
                antwort = msg.get("Reply-To") or msg.get("From", "")
                mails.append(Mail(
                    message_id=msg.get("Message-ID", f"num-{num.decode()}"),
                    absender=parseaddr(antwort)[1].lower(),
                    betreff=str(make_header(decode_header(msg.get("Subject", "")))),
                    text=_text_aus(msg)[:20000],
                ))
        return mails

    def senden(self, g: Gesendet) -> None:
        msg = EmailMessage()
        msg["From"] = f"{self.absender_name} <{self.user}>"
        msg["To"] = g.an
        if g.cc:
            msg["Cc"] = ", ".join(g.cc)
        msg["Subject"] = g.betreff
        msg.set_content(g.text)
        with smtplib.SMTP_SSL(self.smtp_host, 465) as smtp:
            smtp.login(self.user, self.passwort)
            smtp.send_message(msg)


class TestPostfach:
    """Für Tests und Trockenläufe: nichts wird wirklich gesendet."""

    def __init__(self, eingang: list[Mail] | None = None) -> None:
        self.eingang = list(eingang or [])
        self.ausgang: list[Gesendet] = []

    def neue_mails(self, limit: int = 50) -> list[Mail]:
        neu, self.eingang = self.eingang[:limit], self.eingang[limit:]
        return neu

    def senden(self, g: Gesendet) -> None:
        self.ausgang.append(g)
