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


def test_job_board_publish_apply_and_talent_pool(monkeypatch):
    import json as _j
    from urllib.parse import unquote
    from tests.test_deals import _driver
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    monkeypatch.setattr(config, "CONTACT_WHATSAPP", "+49 176 00000000")
    monkeypatch.setattr(config, "CHAT_FIRST", False)
    _driver("Pool Fahrer", "+49 170 3330001", None)
    c = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    r = c.post("/api/stellen", json={"titel": "LKW-Fahrer CE Fernverkehr (m/w/d)", "bereich": "lkw",
                                     "ort": "44137 Dortmund", "gehalt": "ab 3.200 €", "beschreibung": "Touren DE"},
               headers=h).json()
    jid = r["id"]
    page = c.get(f"/jobs/{jid}").text
    assert "JobPosting" in page and "LKW-Fahrer CE Fernverkehr" in page and "stelle=" in page
    ld = _j.loads(page.split('application/ld+json">')[1].split("</script>")[0])
    assert ld["jobLocation"]["address"]["addressCountry"] == "DE"
    assert "LKW-Fahrer CE" in c.get("/jobs").text
    loc = c.get(f"/wa?b=lkw&stelle={jid}&direkt=1", follow_redirects=False).headers["location"]
    assert f"Bewerbung auf Stelle #{jid}" in unquote(loc)
    st = c.get("/api/stellen", headers=h).json()["stellen"]
    assert any(p["name"] == "Pool Fahrer" for s in st if s["id"] == jid for p in s["passend"])
    c.post(f"/api/stellen/{jid}/aktiv", json={"aktiv": False}, headers=h)
    assert c.get(f"/jobs/{jid}", follow_redirects=False).status_code == 302


def test_auto_jobs_from_found_employers_are_anonymous_and_expire():
    from jarvis import jobboard
    conn = store.connect()
    store.add_company(conn, name="Spedition Geheim GmbH", city="59229 Ahlen", phone="+49 231 1",
                      needs="LKW-Fahrer CE Fernverkehr")
    store.add_company(conn, name="Trans Nord KG", city="Ahlen", phone="+49 231 2", needs="Kraftfahrer C Nahverkehr")
    store.add_company(conn, name="Klinik Sonnenberg", city="Thun", phone="+41 31 1", needs="Dipl. Pflegefachperson HF")
    jobboard.sync()
    jobs = {j["auto_key"]: j for j in store.jobs(conn) if j.get("auto_key")}
    lkw = jobs["lkw|ahlen"]
    assert "Raum Ahlen" in lkw["title"] and "2 Speditionen" in lkw["beschreibung"]
    assert "Geheim" not in lkw["beschreibung"] and "Trans Nord" not in lkw["beschreibung"] and not lkw["gehalt"]
    assert "pflege|thun" in jobs
    page = TestClient(server.app).get(f"/jobs/{lkw['id']}").text
    assert "JobPosting" not in page                   # Sammelstellen nicht an Google Jobs
    for name in ("Spedition Geheim GmbH", "Trans Nord KG"):
        cid = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()[0]
        store.set_company_status(conn, cid, "kein_bedarf", "test")
    jobboard.sync()
    assert not store.get_job(conn, lkw["id"])["active"]   # kein Bedarf mehr → offline


def test_jobs_post_to_facebook_page_once_with_daily_limit(monkeypatch):
    from jarvis import ads
    posts = []

    class R:
        status_code = 200
        def json(self): return {"id": f"p{len(posts)}"}
    monkeypatch.setattr(config, "META_PAGE_ID", "123")
    monkeypatch.setattr(config, "META_PAGE_TOKEN", "tok")
    monkeypatch.setattr(ads.requests, "post", lambda url, data, timeout: posts.append(data) or R())
    conn = store.connect()
    store.set_state(conn, f"fb_jobs_today:{__import__('datetime').date.today()}", "0")
    ids = [store.add_job(conn, f"FB-Test Fahrer {i}", "lkw", "Hamm") for i in range(5)]
    for j in store.jobs(conn):
        if j["id"] not in ids:
            store.set_state(conn, f"fb_job:{j['id']}", "x")
    ads.post_open_jobs()
    assert len(posts) == ads.JOB_POSTS_PER_DAY
    assert "/jobs/" in posts[0]["message"] and "#lkwfahrer" in posts[0]["message"]
    ads.post_open_jobs()
    assert len(posts) == ads.JOB_POSTS_PER_DAY                    # Tageslimit, keine Doppelposts
