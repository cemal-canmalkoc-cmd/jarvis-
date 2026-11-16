"""WhatsApp-Versand über Twilio (WhatsApp Business API).

- An dich (Owner): freie Textnachrichten (du schreibst Jarvis zuerst an → 24h-Fenster offen).
- An Kandidaten: nur mit Einwilligung. Erstkontakt per freigegebener Vorlage (Template),
  danach freie Antworten innerhalb des 24h-Fensters.
"""
from __future__ import annotations

import json
import logging

from . import config

log = logging.getLogger("jarvis.whatsapp")
_twilio = None

MAX_LEN = 1500  # WhatsApp-Limit ist 1600 Zeichen


def twilio():
    global _twilio
    if _twilio is None:
        if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
            raise RuntimeError("Twilio ist nicht konfiguriert (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)")
        from twilio.rest import Client
        _twilio = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    return _twilio


def _wa(number: str) -> str:
    number = number.strip()
    if number.startswith("whatsapp:"):
        return number
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"whatsapp:+{digits}"


def _chunks(text: str) -> list[str]:
    parts, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > MAX_LEN and buf:
            parts.append(buf)
            buf = ""
        buf += (("\n" if buf else "") + para)
    if buf:
        parts.append(buf)
    return [p[:MAX_LEN] for p in parts] or [""]


def send_text(to: str, text: str) -> None:
    if not config.TWILIO_WHATSAPP_FROM:
        log.warning("TWILIO_WHATSAPP_FROM fehlt – Nachricht an %s nicht gesendet:\n%s", to, text)
        return
    for chunk in _chunks(text):
        twilio().messages.create(from_=_wa(config.TWILIO_WHATSAPP_FROM), to=_wa(to), body=chunk)


def notify_owner(text: str) -> None:
    """Meldung an dich. Fehler hier dürfen den Ablauf nie stoppen."""
    if not config.OWNER_WHATSAPP:
        log.info("[an Owner] %s", text)
        return
    try:
        send_text(config.OWNER_WHATSAPP, text)
    except Exception as exc:  # noqa: BLE001
        log.error("Owner-Benachrichtigung fehlgeschlagen: %s | %s", exc, text)


def send_first_contact_template(to: str, first_name: str, role: str) -> bool:
    """Erstkontakt per freigegebener WhatsApp-Vorlage. Gibt False zurück, wenn keine Vorlage existiert."""
    if not (config.TWILIO_TEMPLATE_FIRST_CONTACT and config.TWILIO_WHATSAPP_FROM):
        return False
    twilio().messages.create(
        from_=_wa(config.TWILIO_WHATSAPP_FROM),
        to=_wa(to),
        content_sid=config.TWILIO_TEMPLATE_FIRST_CONTACT,
        content_variables=json.dumps({"1": first_name or "", "2": role or "Gesundheitsfachperson"}),
    )
    return True


def is_owner(sender: str) -> bool:
    own = "".join(ch for ch in config.OWNER_WHATSAPP if ch.isdigit())
    snd = "".join(ch for ch in sender if ch.isdigit())
    return bool(own) and own == snd
