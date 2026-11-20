"""Web Push: Verschlüsselung (RFC 8291) gegenprüfen, VAPID, Versand und Aufräumen."""
import json
import struct
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from jarvis import config, messaging, push, server


def _browser_keys():
    priv = ec.generate_private_key(ec.SECP256R1())
    import os
    auth = os.urandom(16)
    return priv, push.b64u(push._pub_bytes(priv.public_key())), push.b64u(auth), auth


def _decrypt(body: bytes, ua_priv, auth: bytes) -> bytes:
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_pub = body[21:21 + idlen]
    assert rs == 4096
    shared = ua_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ua_pub = push._pub_bytes(ua_priv.public_key())
    ikm = push._hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    cek = push._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = push._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_roundtrip():
    priv, p256dh, auth_b64, auth = _browser_keys()
    assert _decrypt(push.encrypt(b'{"hallo":1}', p256dh, auth_b64), priv, auth) == b'{"hallo":1}'


def test_vapid_header_valid_signature():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    h = push._vapid_header("https://web.push.apple.com/abc")
    token, k = h[len("vapid t="):].split(", k=")
    head, claims, sig = token.split(".")
    assert json.loads(push.b64u_dec(claims))["aud"] == "https://web.push.apple.com"
    raw = push.b64u_dec(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.b64u_dec(k))
    pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_subscribe_send_and_cleanup(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    priv, p256dh, auth_b64, auth = _browser_keys()
    got = []

    def fake_post(url, data, headers, timeout):
        got.append(_decrypt(data, priv, auth))
        return SimpleNamespace(status_code=410 if "tot" in url else 201, text="")
    monkeypatch.setattr(push.requests, "post", fake_post)
    c = TestClient(server.app)
    hdr = {"Authorization": "Bearer t0k"}
    assert c.get("/sw.js").status_code == 200
    assert len(push.b64u_dec(c.get("/api/push/key", headers=hdr).json()["key"])) == 65
    r = c.post("/api/push/abo", headers=hdr,
               json={"endpoint": "https://web.push.apple.com/ok", "keys": {"p256dh": p256dh, "auth": auth_b64}})
    assert r.json()["meldung"].startswith("Mitteilungen aktiviert")
    messaging.notify_owner("🔥 2 neue A-Kandidaten\nAnna, Psychiatrie")
    last = json.loads(got[-1])
    assert last["title"] == "🔥 2 neue A-Kandidaten" and "Anna" in last["body"]
    push.subscribe({"endpoint": "https://web.push.apple.com/tot", "keys": {"p256dh": p256dh, "auth": auth_b64}})
    push.send("x", "y")
    assert [s["endpoint"] for s in push.subscriptions()] == ["https://web.push.apple.com/ok"]
