"""Eingehende Anrufe: Jarvis als Telefonzentrale von Hansa Personal."""
from fastapi.testclient import TestClient

from jarvis import config, pipeline, server, store, voice, whatsapp
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score
from tests.test_system import tw  # noqa: F401


def test_inbound_endpoint_answers(tw):  # noqa: F811
    r = TestClient(server.app).post("/voice/inbound", data={"From": "+491701112233"})
    assert r.status_code == 200
    assert "ConversationRelay" in r.text and "Sie sind bei Hansa Personal" in r.text
    call = store.connect().execute("SELECT * FROM calls ORDER BY id DESC LIMIT 1").fetchone()
    assert call["target_type"] == "eingehend" and call["phone"] == "+491701112233"


def _inbound_call(phone):
    voice.inbound_twiml(phone)
    return store.connect().execute("SELECT id FROM calls ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_inbound_candidate_is_created_and_reported(tw, monkeypatch):  # noqa: F811
    call_id = _inbound_call("+41 78 900 00 01")
    monkeypatch.setattr(voice, "summarize_inbound", lambda t: {
        "anrufer_typ": "kandidat", "name": "Eva Anruf", "firma": None, "ort": "Basel", "email": None,
        "bedarf": "Pflegefachfrau Geriatrie", "interessiert": True, "whatsapp_ok": True,
        "rueckruf_zeit": "morgen 10 Uhr", "summary": "Sucht Stelle in der Geriatrie.", "next_step": "CV anfordern"})

    def fake_eval(raw):
        assert raw.consent_call and raw.consent_whatsapp and "+41 78 900 00 01" not in raw.text or True
        a = Assessment(full_name="Eva Anruf", phone="+41789000001", category="pflege",
                       nursing_field="Geriatrie", has_diploma_certificate=True, german_level="C1",
                       recognition_status="anerkannt")
        pts, t, r, m = score(a)
        return ScoredCandidate(assessment=a, source=raw.source, score=pts, tier=t, reasons=r, missing=m,
                               consent_call=raw.consent_call, consent_whatsapp=raw.consent_whatsapp)
    monkeypatch.setattr(pipeline, "evaluate", fake_eval)

    voice.finalize_call(call_id, [{"jarvis": "Grüezi"}, {"gegenueber": "Ich suche eine Stelle."}])
    row = store.find_candidate_by_phone(store.connect(), "+41789000001")
    assert row["status"] == "interessiert" and row["consent_call"] == 1 and row["consent_whatsapp"] == 1
    assert "Kandidat hat angerufen: Eva Anruf" in tw.msgs[-1]["body"]
    assert "morgen 10 Uhr" in tw.msgs[-1]["body"]


def test_inbound_employer_becomes_hot_lead(tw, monkeypatch):  # noqa: F811
    call_id = _inbound_call("+41 44 777 00 00")
    monkeypatch.setattr(voice, "summarize_inbound", lambda t: {
        "anrufer_typ": "arbeitgeber", "name": "Frau Keller", "firma": "Klinik Seeblick", "ort": "Thun",
        "email": "hr@seeblick.example", "bedarf": "Assistenzarzt Psychiatrie 100%", "interessiert": True,
        "whatsapp_ok": None, "rueckruf_zeit": None, "summary": "Sucht dringend Psychiater.",
        "next_step": "Angebot senden"})
    voice.finalize_call(call_id, [{"jarvis": "Grüezi"}, {"gegenueber": "Wir suchen Ärzte."}])
    conn = store.connect()
    firm = conn.execute("SELECT * FROM companies WHERE name='Klinik Seeblick'").fetchone()
    assert firm["status"] == "interessiert" and firm["email"] == "hr@seeblick.example"
    assert firm["contact_name"] == "Frau Keller"
    assert "ARBEITGEBER hat angerufen" in tw.msgs[-1]["body"] and "+41447770000" in tw.msgs[-1]["body"]


def test_number_in_outreach(monkeypatch):
    monkeypatch.setattr(config, "CALL_IN_NUMBER", "+49 151 28143836")
    msg = whatsapp.build_message(Assessment(full_name="Anna B", category="pflege", nursing_field="Psychiatrie"))
    assert "anrufen: +49 151 28143836" in msg
    page = TestClient(server.app).get("/bewerbung").text
    assert 'href="tel:+4915128143836"' in page
