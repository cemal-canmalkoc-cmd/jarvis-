"""Outlook/Hotmail per „Mit Microsoft anmelden" (OAuth2, Gerätecode-Verfahren).

Microsoft lässt bei privaten Outlook-Konten keine Passwort-Anmeldung für Programme mehr zu.
Ablauf: In der App „Mit Microsoft anmelden" → Code auf microsoft.com/link eingeben → fertig.
Jarvis speichert danach ein Erneuerungs-Token und meldet sich selbst an (SMTP + IMAP per XOAUTH2).
Voraussetzung: eine einmal registrierte App-ID (MS_CLIENT_ID) mit „Öffentliche Clientflows" erlaubt.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from . import config, store

log = logging.getLogger("jarvis.msauth")

AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPES = ("offline_access https://outlook.office.com/IMAP.AccessAsUser.All "
          "https://outlook.office.com/SMTP.Send")
_cache: dict = {"token": None, "exp": 0.0}


def configured() -> bool:
    return bool(config.MS_CLIENT_ID)


def connected() -> bool:
    return bool(store.get_state(store.connect(), "ms_refresh_token"))


def is_outlook(host: str) -> bool:
    return "outlook" in (host or "") or "office365" in (host or "")


def start() -> dict:
    """Gerätecode anfordern. Ein Hintergrund-Thread wartet, bis du dich angemeldet hast."""
    if not configured():
        raise RuntimeError("Zuerst unter ⚙️ die Microsoft App-ID eintragen.")
    r = requests.post(f"{AUTHORITY}/devicecode", data={"client_id": config.MS_CLIENT_ID, "scope": SCOPES},
                      timeout=20)
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(f"Microsoft: {data.get('error_description', data)}"[:300])
    threading.Thread(target=_wait_for_login, args=(data["device_code"], int(data.get("interval", 5)),
                                                   int(data.get("expires_in", 900))), daemon=True).start()
    return {"code": data["user_code"], "link": data["verification_uri"],
            "info": f"Öffne {data['verification_uri']}, gib den Code {data['user_code']} ein und melde dich mit "
                    f"deinem Outlook-Konto an. Jarvis meldet sich, sobald es geklappt hat."}


def _save(tok: dict) -> None:
    conn = store.connect()
    if tok.get("refresh_token"):
        store.set_state(conn, "ms_refresh_token", tok["refresh_token"])
    _cache["token"] = tok["access_token"]
    _cache["exp"] = time.time() + int(tok.get("expires_in", 3600)) - 120


def _wait_for_login(device_code: str, interval: int, expires: int) -> None:
    from . import messaging
    end = time.time() + expires
    while time.time() < end:
        time.sleep(interval)
        try:
            r = requests.post(f"{AUTHORITY}/token", timeout=20, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": config.MS_CLIENT_ID, "device_code": device_code})
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.error("Microsoft-Anmeldung: %s", exc)
            continue
        err = data.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            messaging.notify_owner(f"❌ Microsoft-Anmeldung fehlgeschlagen: {data.get('error_description', err)[:200]}")
            return
        _save(data)
        messaging.notify_owner("✅ Outlook verbunden – Jarvis kann jetzt Mails senden und lesen. "
                               "Tipp: ⚙️ → Testmail.")
        return
    messaging.notify_owner("⌛ Microsoft-Anmeldung abgelaufen – bitte noch mal „Mit Microsoft anmelden“ tippen.")


def access_token() -> str:
    """Gültiges Zugangs-Token (wird bei Bedarf mit dem Erneuerungs-Token geholt)."""
    if _cache["token"] and time.time() < _cache["exp"]:
        return _cache["token"]
    refresh = store.get_state(store.connect(), "ms_refresh_token")
    if not refresh or not configured():
        raise RuntimeError("Outlook ist nicht verbunden – App → ⚙️ → „Mit Microsoft anmelden“.")
    r = requests.post(f"{AUTHORITY}/token", timeout=20, data={
        "grant_type": "refresh_token", "client_id": config.MS_CLIENT_ID, "refresh_token": refresh,
        "scope": SCOPES})
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError("Outlook-Anmeldung abgelaufen – bitte erneut „Mit Microsoft anmelden“: "
                           + str(data.get("error_description", ""))[:150])
    _save(data)
    return _cache["token"]


def xoauth2(user: str) -> str:
    return f"user={user}\x01auth=Bearer {access_token()}\x01\x01"
