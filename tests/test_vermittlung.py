"""Sparmodus, Meta-WhatsApp, Vermittlung (Matching, anonyme Vorstellung, Nachfassen)."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from jarvis import agent, autopilot, brain, config, matching, messaging, server, store
from tests.test_system import add_candidate, tw  # noqa: F401


def test_sparmodus_defaults():
    assert config.SPARMODUS and config.MODEL == "claude-haiku-5-5"
    assert brain.fallback_kwargs("claude-haiku-5-5") == {}
    assert brain.fallback_kwargs("claude-opus-5-5")["fallbacks"] == "default"
    assert brain.web_search_tool("claude-haiku-5-5", 3)["type"] == "web_search_20250305"
    assert brain.web_search_tool("claude-opus-5-5", 3)["type"] == "web_search_20260209"


# ------------------------------------------------------------------ Meta WhatsApp
def _meta_cfg(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(config, "META_TOKEN", "t")
    monkeypatch.setattr(config, "META_PHONE_NUMBER_ID", "123")
    monkeypatch.setattr(config, "META_APP_SECRET", "appsecret")
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", "verify-me")
    monkeypatch.setattr(config, "VALIDATE_TWILIO", True)
    monkeypatch.setattr(config, "OWNER_WHATSAPP", "+491700000000")
    sent = []
    monkeypatch.setattr(messaging, "_meta_post", lambda payload: sent.append(payload))
    return sent


def test_meta_webhook_verification(monkeypatch):
    _meta_cfg(monkeypatch)
    c = TestClient(server.app)
    ok = c.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                    "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                      "hub.challenge": "42"}).status_code == 403


def test_meta_owner_message_signed(monkeypatch):
    sent = _meta_cfg(monkeypatch)
    monkeypatch.setattr(agent, "handle_owner", lambda t: f"Antwort auf: {t}")
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "491700000000", "type": "text", "text": {"body": "Tagesbericht"}}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"appsecret", raw, hashlib.sha256).hexdigest()
    c = TestClient(server.app)
    bad = c.post("/whatsapp", content=raw, headers={"Content-Type": "application/json",
                                                    "X-Hub-Signature-256": "sha256=falsch"})
    assert bad.status_code == 403 and not sent
    r = c.post("/whatsapp", content=raw, headers={"Content-Type": "application/json",
                                                  "X-Hub-Signature-256": sig})
    assert r.status_code == 200
    assert sent[-1] == {"to": "491700000000", "type": "text", "text": {"body": "Antwort auf: Tagesbericht"}}


def test_meta_template_payload(monkeypatch):
    sent = _meta_cfg(monkeypatch)
    monkeypatch.setattr(config, "META_TEMPLATE_FIRST_CONTACT", "erstkontakt")
    assert messaging.send_first_contact_template("+41 79 1", "Anna", "Pflegefachperson")
    t = sent[-1]["template"]
    assert t["name"] == "erstkontakt" and t["components"][0]["parameters"][0]["text"] == "Anna"


# ------------------------------------------------------------------ Vermittlung
def _firm(name, city, needs, email=None):
    conn = store.connect()
    store.add_company(conn, name=name, city=city, needs=needs, phone="+41 44 111 11 11")
    cid = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()[0]
    if email:
        store.set_company_contact(conn, cid, email, "Frau Huber")
    return cid


def test_matching_finds_right_clinic(tw):  # noqa: F811
    key = add_candidate(phone="+41 79 444 00 01", full_name="Paula Psych", nursing_field="Psychiatrie",
                        current_location="Zürich")
    good = _firm("Psychiatrie Nord", "Zürich", "Dipl. Pflegefachperson Psychiatrie 80-100%")
    _firm("Radiologie Süd", "Lugano", "Facharzt Radiologie")
    m = matching.matches(store.connect(), store.get_candidate(store.connect(), key))
    assert m and m[0]["id"] == good and all(x["name"] != "Radiologie Süd" for x in m)


def test_present_requires_interest_and_is_anonymous(tw, monkeypatch):  # noqa: F811
    key = add_candidate(phone="+41 79 444 00 02", full_name="Vera Vertraulich", nursing_field="Psychiatrie")
    cid = _firm("Klinik Mail", "Bern", "Pflege Psychiatrie", email="hr@klinik.example")
    assert "noch kein Interesse" in matching.present(key, cid)

    store.set_status(store.connect(), key[:6], "interessiert")  # abgekürzte ID
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, subj, body: mails.append((to, subj, body)))
    msg = matching.present(key, cid)
    assert msg.startswith("✅") and mails[0][0] == "hr@klinik.example"
    body = mails[0][2]
    assert "Vera" not in body and "+41" not in body          # anonym
    assert "Frau Huber" in body and "Hansa Personal" in body and "SRK-Anerkennung: liegt vor" in body


def test_present_without_email_gives_copy_text(tw):  # noqa: F811
    key = add_candidate(phone="+41 79 444 00 03", nursing_field="Geriatrie")
    store.set_status(store.connect(), key, "interessiert")
    cid = _firm("Heim ohne Mail", "Luzern", "Pflege Langzeitpflege")
    assert "Text zum Kopieren" in matching.present(key, cid)


def test_followups_due(tw):  # noqa: F811
    key = add_candidate(phone="+41 79 444 00 04", full_name="Nora Nachfass")
    conn = store.connect()
    store.set_status(conn, key, "kontaktiert")
    old = (datetime.now() - timedelta(days=4)).isoformat(timespec="minutes")
    conn.execute("UPDATE candidates SET last_contact=? WHERE key=?", (old, key))
    conn.commit()
    assert any(r["key"] == key for r in store.followups_due(conn))


def test_morning_report_without_telephony(tw, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "TWILIO_VOICE_FROM", "")
    monkeypatch.setattr(config, "DAILY_TARGET", 0)
    monkeypatch.setattr(autopilot.pipeline, "run", lambda **kw: {"geprueft": 0})
    monkeypatch.setattr(autopilot.companies, "find", lambda *a, **k: {"neu": 0})
    add_candidate(phone="+41 79 444 00 05", full_name="Ida Liste")
    autopilot.morning(force=True)
    report = tw.msgs[-1]["body"]
    assert "Morgenbericht" in report and "Deine Anrufliste heute" in report and "/app" in report
    assert autopilot.call_round()["info"] == "keine Telefonie eingerichtet"


def test_app_shows_matches_and_script(tw, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    key = add_candidate(phone="+41 79 444 00 06", nursing_field="Psychiatrie", german_level="unbekannt")
    _firm("Psychiatrie West", "Basel", "Pflegefachperson Psychiatrie")
    d = TestClient(server.app).get(f"/api/kandidat/{key}", headers={"Authorization": "Bearer t0k"}).json()
    assert any(f["name"] == "Psychiatrie West" for f in d["passende_firmen"])
    assert any("Deutsch-Zertifikat" in q for q in d["leitfaden"])
    assert "Cemal-Can Malkoc" in d["leitfaden"][0]
