"""Systemtests mit simuliertem Claude und Twilio (keine echten Anrufe/Nachrichten)."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jarvis import agent, config, messaging, pipeline, server, store, voice
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score


# ------------------------------------------------------------------ Hilfen
class Block(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        return {k: v for k, v in vars(self).items() if not (exclude_none and v is None)}


def add_candidate(phone="+41 79 555 11 22", consent_call=True, consent_wa=False, **kw):
    base = dict(full_name="Lena Test", phone=phone, category="pflege", nursing_field="Akutspital",
                has_diploma_certificate=True, german_level="C1", recognition_status="anerkannt",
                currently_in_switzerland=True)
    base.update(kw)
    a = Assessment(**base)
    pts, tier, reasons, missing = score(a)
    c = ScoredCandidate(assessment=a, source="test", score=pts, tier=tier, reasons=reasons,
                        missing=missing, consent_call=consent_call, consent_whatsapp=consent_wa)
    store.upsert(store.connect(), c)
    return store.candidate_key(c)


class FakeTwilio:
    def __init__(self):
        self.calls_made, self.msgs = [], []
        self.calls = SimpleNamespace(create=self._call)
        self.messages = SimpleNamespace(create=self._msg)

    def _call(self, **kw):
        self.calls_made.append(kw)
        return SimpleNamespace(sid="CA123")

    def _msg(self, **kw):
        self.msgs.append(kw)


@pytest.fixture
def tw(monkeypatch):
    fake = FakeTwilio()
    monkeypatch.setattr(messaging, "_twilio", fake)
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "TWILIO_VOICE_FROM", "+41440000000")
    monkeypatch.setattr(config, "TWILIO_WHATSAPP_FROM", "+41440000001")
    monkeypatch.setattr(config, "OWNER_WHATSAPP", "+491700000000")
    monkeypatch.setattr(config, "VALIDATE_TWILIO", False)
    monkeypatch.setattr(voice, "within_call_hours", lambda now=None: True)
    return fake


# ------------------------------------------------------------------ Regeln
def test_call_hours():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.TIMEZONE)
    assert voice.within_call_hours(datetime(2026, 11, 16, 10, tzinfo=tz))      # Montag
    assert not voice.within_call_hours(datetime(2026, 11, 21, 10, tzinfo=tz))  # Samstag
    assert not voice.within_call_hours(datetime(2026, 11, 16, 19, tzinfo=tz))


def test_hangup_filter_split_tokens():
    f = voice._HangupFilter()
    out = "".join(f.feed(t) for t in ["Auf Wiederhören! ", "[AUF", "LEGEN", "]"]) + f.flush()
    assert out == "Auf Wiederhören! " and f.hangup


def test_no_call_without_consent(tw):
    key = add_candidate(phone="+41 79 111 00 01", consent_call=False)
    msg = voice.place_call("kandidat", key)
    assert "keine Anruf-Einwilligung" in msg and not tw.calls_made


def test_no_call_when_opted_out(tw):
    key = add_candidate(phone="+41 79 111 00 02")
    store.add_optout(store.connect(), "+41791110002")
    assert "Sperrliste" in voice.place_call("kandidat", key) and not tw.calls_made


def test_call_and_twiml(tw):
    key = add_candidate(phone="+41 79 111 00 03")
    msg = voice.place_call("kandidat", key)
    assert "Rufe Lena Test an" in msg
    kw = tw.calls_made[0]
    assert kw["to"] == "+41791110003" and kw["machine_detection"] == "Enable"
    call_id = int(kw["url"].split("call_id=")[1])
    assert "<Hangup" in voice.twiml_for(call_id, "machine_end_beep")
    xml = voice.twiml_for(call_id, "human")
    assert "ConversationRelay" in xml and "KI-Assistent" in xml and "call_id" in xml


# ------------------------------------------------------------------ Live-Gespräch
class FakeStream:
    def __init__(self, tokens):
        self.tokens = tokens

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def text_stream(self):
        async def gen():
            for t in self.tokens:
                yield t
        return gen()

    async def get_final_message(self):
        return SimpleNamespace(content=[Block(type="text", text="".join(self.tokens))],
                               stop_reason="end_turn")


def test_relay_session_conversation(tw, monkeypatch):
    key = add_candidate(phone="+41 79 111 00 04")
    voice.place_call("kandidat", key)
    call_id = int(tw.calls_made[-1]["url"].split("call_id=")[1])

    replies = iter([["Schön! ", "Ab wann ", "wären Sie verfügbar?"],
                    ["Danke, wir melden uns. ", "Auf Wiederhören! [AUFLEGEN]"]])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kw: FakeStream(next(replies)))))
    monkeypatch.setattr(voice, "aclient", lambda: fake)
    monkeypatch.setattr(voice, "END_DELAY_S", 0)
    monkeypatch.setattr(voice, "summarize", lambda t, tr: {
        "outcome": "interessiert", "summary": "Will in die Schweiz.", "next_step": "Rückruf",
        "callback_time": "Mi 14 Uhr", "contact_name": None, "contact_email": None})

    sent = []

    async def send(m):
        sent.append(m)

    async def run():
        s = voice.RelaySession(send)
        await s.handle({"type": "setup", "customParameters": {"call_id": str(call_id)}})
        await s.handle({"type": "prompt", "voicePrompt": "Ja, passt.", "last": True})
        await s.task
        await s.handle({"type": "prompt", "voicePrompt": "Ab März.", "last": True})
        await s.task
        return s

    s = asyncio.run(run())
    spoken = "".join(m.get("token", "") for m in sent if m["type"] == "text")
    assert "[AUFLEGEN]" not in spoken and "Auf Wiederhören!" in spoken
    assert sent[-1]["type"] == "end"
    assert [m["role"] for m in s.messages] == ["user", "assistant", "user", "assistant"]
    s.finish()
    conn = store.connect()
    assert store.get_candidate(conn, key)["status"] == "interessiert"
    assert any("🔥" in m["body"] for m in tw.msgs)  # Owner benachrichtigt


# ------------------------------------------------------------------ Server
def test_form_submission(tw, monkeypatch):
    seen = {}

    def fake_eval(raw):
        seen["raw"] = raw
        a = Assessment(full_name="Max Form", phone="+41 79 222 33 44", category="arzt",
                       physician_specialty="Radiologie", german_level="C1",
                       recognition_status="anerkannt")
        pts, tier, r, m = score(a)
        return ScoredCandidate(assessment=a, source=raw.source, score=pts, tier=tier, reasons=r,
                               missing=m, consent_call=raw.consent_call,
                               consent_whatsapp=raw.consent_whatsapp)

    monkeypatch.setattr(pipeline, "evaluate", fake_eval)
    client = TestClient(server.app)
    assert "Ihre Stelle in der Schweiz" in client.get("/bewerbung").text
    r = client.post("/bewerbung", data={
        "name": "Max Form", "phone": "+41 79 222 33 44", "wohnort": "Bern",
        "bereich": "Ärztin/Arzt Radiologie", "consent_data": "1", "consent_call": "1"},
        files={"cv": ("cv.txt", b"Facharzt Radiologie, MEBEKO anerkannt", "text/plain")})
    assert r.status_code == 200 and "Vielen Dank, Max" in r.text and "wa.me/41440000001" in r.text
    assert seen["raw"].consent_call and not seen["raw"].consent_whatsapp
    assert "MEBEKO anerkannt" in seen["raw"].text
    row = store.find_candidate_by_phone(store.connect(), "+41792223344")
    assert row["consent_call"] == 1
    assert any(c["to"] == "+41792223344" for c in tw.calls_made)  # heisser Bewerber sofort angerufen


def test_form_requires_consent(tw):
    r = TestClient(server.app).post("/bewerbung", data={
        "name": "X", "phone": "1", "wohnort": "Y", "bereich": "Z"})
    assert r.status_code == 400


def test_whatsapp_owner_routing(tw, monkeypatch):
    monkeypatch.setattr(agent, "handle_owner", lambda text: f"Echo: {text}")
    r = TestClient(server.app).post("/whatsapp", data={"From": "whatsapp:+491700000000",
                                                       "Body": "Tagesbericht", "NumMedia": "0"})
    assert r.status_code == 200
    assert tw.msgs[-1]["body"] == "Echo: Tagesbericht" and tw.msgs[-1]["to"] == "whatsapp:+491700000000"


def test_whatsapp_candidate_stop(tw):
    key = add_candidate(phone="+41 79 111 00 05")
    TestClient(server.app).post("/whatsapp", data={"From": "whatsapp:+41791110005", "Body": "STOP",
                                                   "NumMedia": "0"})
    conn = store.connect()
    assert store.is_opted_out(conn, "+41791110005")
    assert store.get_candidate(conn, key)["status"] == "kein_interesse"
    assert "nicht mehr" in tw.msgs[-1]["body"]


def test_twilio_signature_enforced(monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_TWILIO", True)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "tok")
    r = TestClient(server.app).post("/whatsapp", data={"From": "whatsapp:+1", "Body": "x"})
    assert r.status_code == 403


def test_shortlist_requires_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "geheim")
    c = TestClient(server.app)
    assert c.get("/shortlist").status_code == 401
    assert c.get("/shortlist?token=geheim").status_code == 200


# ------------------------------------------------------------------ Owner-Agent
def test_owner_agent_tool_loop(tw, monkeypatch):
    responses = iter([
        SimpleNamespace(stop_reason="tool_use", content=[
            Block(type="tool_use", id="tu1", name="tagesbericht", input={})]),
        SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="Heute 3 von 20.")]),
    ])
    captured = []

    def create(**kw):
        captured.append(json.loads(json.dumps(kw["messages"], default=str)))
        return next(responses)

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(agent.brain, "client", lambda: fake)
    assert agent.handle_owner("Wie läuft's?") == "Heute 3 von 20."
    tool_result = captured[1][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "ziel_pro_tag" in tool_result["content"]
    history, _ = store.load_chat(store.connect(), config.OWNER_WHATSAPP)
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
