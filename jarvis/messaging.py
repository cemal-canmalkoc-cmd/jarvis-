"""WhatsApp-Versand.

Anbieter (JARVIS_WHATSAPP_PROVIDER):
- "meta" (Standard): WhatsApp Cloud API direkt bei Meta. Antworten in Gesprächen, die der
  Kandidat (oder du) begonnen hat, sind kostenlos. Nur Erstkontakt-Vorlagen kosten wenige Rappen.
- "twilio": über Twilio (Twilio-Gebühr kommt dazu).

Regeln: An dich frei. An Kandidaten nur mit Einwilligung; Erstkontakt per freigegebener Vorlage,
danach freie Antworten innerhalb des 24h-Fensters.
"""
from __future__ import annotations

import json
import logging

import requests

from . import config

log = logging.getLogger("jarvis.whatsapp")
_twilio = None

MAX_LEN = 1500


# --------------------------------------------------------------------------- Hilfen
def digits(number: str) -> str:
    return "".join(ch for ch in (number or "") if ch.isdigit())


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


def jarvis_number() -> str:
    """Jarvis' eigene WhatsApp-Nummer (für 'Chat starten'-Links)."""
    return digits(config.JARVIS_WHATSAPP_NUMBER or config.TWILIO_WHATSAPP_FROM)


def is_owner(sender: str) -> bool:
    own = digits(config.OWNER_WHATSAPP)
    return bool(own) and own == digits(sender)


# --------------------------------------------------------------------------- Twilio
def twilio():
    global _twilio
    if _twilio is None:
        if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
            raise RuntimeError("Twilio ist nicht konfiguriert (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)")
        from twilio.rest import Client
        _twilio = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    return _twilio


def _wa(number: str) -> str:
    return number if number.startswith("whatsapp:") else f"whatsapp:+{digits(number)}"


# --------------------------------------------------------------------------- Meta Cloud API
def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/{path}"


def _meta_post(payload: dict) -> None:
    r = requests.post(_graph(f"{config.META_PHONE_NUMBER_ID}/messages"),
                      headers={"Authorization": f"Bearer {config.META_TOKEN}"},
                      json={"messaging_product": "whatsapp", **payload}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Meta-API-Fehler {r.status_code}: {r.text[:300]}")


def meta_download(media_id: str) -> tuple[bytes, str]:
    h = {"Authorization": f"Bearer {config.META_TOKEN}"}
    info = requests.get(_graph(media_id), headers=h, timeout=30)
    info.raise_for_status()
    meta = info.json()
    data = requests.get(meta["url"], headers=h, timeout=60)
    data.raise_for_status()
    return data.content, meta.get("mime_type", "")


def _configured() -> bool:
    if config.WHATSAPP_PROVIDER == "twilio":
        return bool(config.TWILIO_WHATSAPP_FROM)
    return bool(config.META_TOKEN and config.META_PHONE_NUMBER_ID)


# --------------------------------------------------------------------------- Senden
def send_text(to: str, text: str) -> None:
    if not _configured():
        log.warning("WhatsApp nicht eingerichtet – Nachricht an %s nicht gesendet:\n%s", to, text)
        return
    for chunk in _chunks(text):
        if config.WHATSAPP_PROVIDER == "twilio":
            twilio().messages.create(from_=_wa(config.TWILIO_WHATSAPP_FROM), to=_wa(to), body=chunk)
        else:
            _meta_post({"to": digits(to), "type": "text", "text": {"body": chunk}})


def owner_reachable_by_whatsapp() -> bool:
    """Jarvis kann dir nicht von deiner eigenen Nummer aus schreiben."""
    own = digits(config.OWNER_WHATSAPP)
    return bool(own) and own != jarvis_number()


def notify_owner(text: str) -> None:
    """Meldung an dich: immer ins App-Postfach, dazu WhatsApp (oder E-Mail, falls WhatsApp nicht geht).
    Fehler hier dürfen den Ablauf nie stoppen."""
    try:
        from . import store
        store.add_notification(store.connect(), text)
    except Exception as exc:  # noqa: BLE001
        log.error("Meldung nicht gespeichert: %s", exc)
    try:
        if owner_reachable_by_whatsapp():
            send_text(config.OWNER_WHATSAPP, text)
        elif config.OWNER_EMAIL and config.SMTP_HOST:
            from .matching import send_email
            send_email(config.OWNER_EMAIL, "Jarvis: " + text.split("\n")[0][:80], text)
        else:
            log.info("[an Owner] %s", text)
    except Exception as exc:  # noqa: BLE001
        log.error("Owner-Benachrichtigung fehlgeschlagen: %s | %s", exc, text)


def send_first_contact_template(to: str, first_name: str, role: str) -> bool:
    """Erstkontakt per freigegebener Vorlage. False, wenn keine Vorlage eingerichtet ist."""
    first_name, role = first_name or "", role or "Gesundheitsfachperson"
    if config.WHATSAPP_PROVIDER == "twilio":
        if not (config.TWILIO_TEMPLATE_FIRST_CONTACT and config.TWILIO_WHATSAPP_FROM):
            return False
        twilio().messages.create(
            from_=_wa(config.TWILIO_WHATSAPP_FROM), to=_wa(to),
            content_sid=config.TWILIO_TEMPLATE_FIRST_CONTACT,
            content_variables=json.dumps({"1": first_name, "2": role}))
        return True
    if not (config.META_TEMPLATE_FIRST_CONTACT and _configured()):
        return False
    _meta_post({"to": digits(to), "type": "template", "template": {
        "name": config.META_TEMPLATE_FIRST_CONTACT,
        "language": {"code": config.META_TEMPLATE_LANG},
        "components": [{"type": "body", "parameters": [
            {"type": "text", "text": first_name}, {"type": "text", "text": role}]}],
    }})
    return True
