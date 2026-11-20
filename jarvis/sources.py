"""Kandidatenquellen.

1. Ordner data/inbox/: Lebensläufe (PDF, DOCX, TXT) – z.B. Bewerbungen, Exporte aus
   Jobportalen, auf denen ihr einen Recruiter-Zugang habt, Empfehlungen.
2. E-Mail-Postfach (IMAP): Bewerbungen mit Lebenslauf im Anhang.
3. Web: öffentliche Stellengesuche (siehe brain.find_public_leads).
"""
from __future__ import annotations

import email
import imaplib
import io
import os
import shutil
from dataclasses import dataclass
from email.header import decode_header
from pathlib import Path

from .config import INBOX_DIR, PROCESSED_DIR


@dataclass
class RawProfile:
    source: str
    text: str
    file: Path | None = None
    # Einwilligungen: Formular = ausdrücklich angehakt; Bewerbung per Mail/Ordner = Anruf zur
    # Bewerbung ok; öffentliche Web-Funde = nur manueller Kontakt durch dich.
    consent_whatsapp: bool = False
    consent_call: bool = False


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _docx_text(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs)


def file_to_text(name: str, data: bytes) -> str | None:
    n = name.lower()
    if n.endswith(".pdf"):
        return _pdf_text(data)
    if n.endswith(".docx"):
        return _docx_text(data)
    if n.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    return None


def from_inbox_folder() -> list[RawProfile]:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(INBOX_DIR.iterdir()):
        if not f.is_file():
            continue
        text = file_to_text(f.name, f.read_bytes())
        if text and text.strip():
            out.append(RawProfile(source=f"Datei: {f.name}", text=text, file=f, consent_call=True))
    return out


def archive(profile: RawProfile) -> None:
    if profile.file and profile.file.exists():
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(profile.file), PROCESSED_DIR / profile.file.name)


def _decode(s: str | None) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    return "".join(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
                   for p, enc in parts)


def from_email() -> list[RawProfile]:
    """Liest ungelesene Bewerbungs-Mails. Konfiguration über Umgebungsvariablen:
    JARVIS_IMAP_HOST, JARVIS_IMAP_USER, JARVIS_IMAP_PASSWORD, JARVIS_IMAP_FOLDER (Standard INBOX)."""
    host = os.environ.get("JARVIS_IMAP_HOST")
    from . import inbox
    if not host or inbox.ready():  # das Postfach bearbeitet dann inbox.poll (liest + antwortet)
        return []
    box = imaplib.IMAP4_SSL(host)
    box.login(os.environ["JARVIS_IMAP_USER"], os.environ["JARVIS_IMAP_PASSWORD"])
    box.select(os.environ.get("JARVIS_IMAP_FOLDER", "INBOX"))
    _, ids = box.search(None, "UNSEEN")
    out = []
    for mid in ids[0].split():
        _, msg_data = box.fetch(mid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        sender = _decode(msg.get("From"))
        subject = _decode(msg.get("Subject"))
        texts = [f"Absender: {sender}\nBetreff: {subject}"]
        for part in msg.walk():
            fname = part.get_filename()
            payload = part.get_payload(decode=True)
            if fname and payload:
                t = file_to_text(_decode(fname), payload)
                if t:
                    texts.append(f"--- Anhang {fname} ---\n{t}")
            elif part.get_content_type() == "text/plain" and payload:
                texts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        out.append(RawProfile(source=f"E-Mail: {sender} – {subject}", text="\n\n".join(texts),
                              consent_call=True))
    box.logout()
    return out
