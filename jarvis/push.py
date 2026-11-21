"""Push-Mitteilungen aufs iPhone (Web Push, kostenlos).

Funktioniert für die Jarvis-App auf dem Home-Bildschirm (iOS 16.4+). Umsetzung nach
RFC 8291 (Verschlüsselung aes128gcm) und RFC 8292 (VAPID) – ohne Zusatzbibliothek.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import struct
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import store

log = logging.getLogger("jarvis.push")
SUBJECT = "mailto:jarvis@hansa-personal.invalid"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _pub_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# --------------------------------------------------------------------------- VAPID-Schlüssel
def vapid_private() -> ec.EllipticCurvePrivateKey:
    conn = store.connect()
    pem = store.get_state(conn, "vapid_private")
    if not pem:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        store.set_state(conn, "vapid_private", pem)
    return serialization.load_pem_private_key(pem.encode(), password=None)


def vapid_public_b64() -> str:
    return b64u(_pub_bytes(vapid_private().public_key()))


def _vapid_header(endpoint: str) -> str:
    u = urlparse(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                              "sub": SUBJECT}).encode())
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(vapid_private().sign(signing_input, ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={vapid_public_b64()}"


# --------------------------------------------------------------------------- Verschlüsselung (RFC 8291)
def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    ua_pub_bytes = b64u_dec(p256dh)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_bytes)
    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub_bytes = _pub_bytes(as_priv.public_key())
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    ikm = _hkdf(b64u_dec(auth), shared, b"WebPush: info\x00" + ua_pub_bytes + as_pub_bytes, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub_bytes)) + as_pub_bytes + ciphertext


# --------------------------------------------------------------------------- Abos & Versand
def subscriptions() -> list[dict]:
    raw = store.get_state(store.connect(), "push_subs")
    return json.loads(raw) if raw else []


def _save(subs: list[dict]) -> None:
    store.set_state(store.connect(), "push_subs", json.dumps(subs))


def subscribe(sub: dict) -> None:
    if not (sub.get("endpoint") and sub.get("keys", {}).get("p256dh") and sub.get("keys", {}).get("auth")):
        raise ValueError("Ungültiges Push-Abo")
    subs = [s for s in subscriptions() if s["endpoint"] != sub["endpoint"]]
    subs.append({"endpoint": sub["endpoint"], "keys": sub["keys"]})
    _save(subs)


def send(title: str, body: str, url: str = "/app") -> int:
    """Schickt eine Mitteilung an alle eingetragenen Geräte. Gibt die Anzahl Erfolge zurück."""
    subs = subscriptions()
    if not subs:
        return 0
    payload = json.dumps({"title": title, "body": body[:400], "url": url}).encode()
    ok, keep = 0, []
    for s in subs:
        try:
            r = requests.post(s["endpoint"], data=encrypt(payload, s["keys"]["p256dh"], s["keys"]["auth"]),
                              headers={"Authorization": _vapid_header(s["endpoint"]), "TTL": "86400",
                                       "Content-Encoding": "aes128gcm", "Urgency": "high",
                                       "Content-Type": "application/octet-stream"}, timeout=15)
            if r.status_code in (404, 410):
                continue  # Abo abgelaufen → entfernen
            keep.append(s)
            if r.status_code < 300:
                ok += 1
            else:
                log.error("Push abgelehnt %s: %s", r.status_code, r.text[:200])
        except Exception as exc:  # noqa: BLE001
            keep.append(s)
            log.error("Push fehlgeschlagen: %s", exc)
    if len(keep) != len(subs):
        _save(keep)
    return ok
