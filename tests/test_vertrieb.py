"""Eigener Vertrieb: WhatsApp-Links, Firmen-Seite, Bewerbungen auf Stellenanzeigen."""
from fastapi.testclient import TestClient

from jarvis import config, deals, matching, server, store
from tests.test_deals import _driver


def test_whatsapp_redirect_counts(monkeypatch):
    monkeypatch.setattr(config, "CONTACT_WHATSAPP", "+49 176 00000000")
    monkeypatch.setattr(config, "CHAT_FIRST", False)
    c = TestClient(server.app)
    r = c.get("/wa?b=lkw&q=test", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://wa.me/4917600000000?text=")
    assert "LKW-Fahrer" in __import__("urllib.parse").parse.unquote(r.headers["location"])
    from datetime import date
    assert int(store.get_state(store.connect(), f"clicks:{date.today()}:lkw")) >= 1
    assert "direkt per WhatsApp" in c.get("/bewerbung?bereich=lkw").text
    assert "direkt per WhatsApp" in c.get("/bewerbung").text


def test_employer_page_creates_hot_lead_and_sends_offer(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, b)))
    _driver("Lead Fahrer", "+49 170 9990001", None)
    c = TestClient(server.app)
    assert "Sie zahlen nur bei Einstellung" in c.get("/firmen").text
    r = c.post("/firmen", data={"firma": "Trans Lead GmbH", "ort": "Dortmund", "email": "chef@translead.example",
                                "bereich": "lkw", "bedarf": "2 CE-Fahrer Fernverkehr", "consent": "1"})
    assert r.status_code == 200 and "Vielen Dank" in r.text
    firm = store.connect().execute("SELECT * FROM companies WHERE name='Trans Lead GmbH'").fetchone()
    assert firm["status"] == "interessiert" and firm["agreement"]
    assert mails and mails[-1][0] == "chef@translead.example" and "VERMITTLUNGSVEREINBARUNG" in mails[-1][1]
    assert "NEUE FIRMENANFRAGE" in store.notifications(store.connect(), 1)[0]["text"]


def test_job_ad_applications_need_approval(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s, b)))
    monkeypatch.setattr(config, "AUTO_APPLY", False)
    key = _driver("Anzeigen Fahrer", "+49 170 9990002", None)
    conn = store.connect()
    store.add_company(conn, name="Spedition Anzeige", city="Dortmund", needs="LKW-Fahrer CE Fernverkehr",
                      email="bewerbung@anzeige.example", branche="lkw")
    q = deals.application_queue()
    item = next(x for x in q if x["firma"] == "Spedition Anzeige")
    deals.daily_drive()
    assert not any(m[0] == "bewerbung@anzeige.example" for m in mails)       # ohne Freigabe nichts gesendet
    assert "Bewerbungen auf Stellenanzeigen bereit" in store.notifications(conn, 1)[0]["text"]
    msg = deals.send_application(item["kandidat_id"], item["firma_id"])
    assert msg.startswith("✅")
    to, subj, body = next(m for m in mails if m[0] == "bewerbung@anzeige.example")
    assert "bezugnehmend auf Ihre Stellenanzeige" in body and "Anzeigen Fahrer" not in body and "Kein Interesse" in body
    assert store.get_company(conn, item["firma_id"])["status"] == "angeschrieben"
    assert all(x["firma_id"] != item["firma_id"] for x in deals.application_queue())   # nicht doppelt
    assert store.get_candidate(conn, item["kandidat_id"])["status"] == "vorgestellt"
    assert key


def test_referral_page_and_tracked_link(monkeypatch):
    from urllib.parse import unquote
    monkeypatch.setattr(config, "CONTACT_WHATSAPP", "+49 176 00000000")
    monkeypatch.setattr(config, "CHAT_FIRST", False)
    monkeypatch.setattr(config, "REFERRAL_BONUS_LKW", "200 €")
    c = TestClient(server.app)
    page = c.get("/empfehlen?b=lkw").text
    assert "Kennst du LKW-Fahrer" in page and "200 €" in page and "wa.me/?text=" in page
    assert "1.000 €" in c.get("/empfehlen?b=pflege").text
    r = c.get("/wa?b=lkw&q=empfehlung&ref=Ali%20K.", follow_redirects=False)
    assert "Empfohlen von: Ali K." in unquote(r.headers["location"])


def test_deep_search_asks_cost_first(monkeypatch):
    from jarvis import autopilot
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    started = []
    monkeypatch.setattr(autopilot, "deep_search", lambda b: started.append(b))
    c = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    q = c.post("/api/tiefensuche", json={"bereich": "lkw"}, headers=h).json()
    assert q["kosten"] > 0 and q["suchen"] >= 10 and not started
    assert all(f.lower().startswith("lkw:") for f in autopilot.deep_focuses("lkw"))
    c.post("/api/tiefensuche", json={"bereich": "lkw", "bestaetigt": True}, headers=h)
    import time; time.sleep(0.2)
    assert started == ["lkw"]
