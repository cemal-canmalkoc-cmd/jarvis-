"""Vermittlungs-Ablauf: Dokumente → Firma mit Interesse → Vereinbarung → Unterlagen → Einstellung → Rechnung."""
from datetime import date

from fastapi.testclient import TestClient

from jarvis import config, deals, matching, server, store
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score


def _driver(name="Paul Profi", phone="+49 170 8880001", email="paul@example.org"):
    a = Assessment(full_name=name, phone=phone, email=email, category="lkw", driving_license="CE",
                   driver_card=True, code95=True, adr=False, traffic_type="Fernverkehr", years_experience=5,
                   german_level="muttersprache", current_location="44137 Dortmund", summary=f"{name} Fahrer")
    p, t, r, m = score(a)
    c = ScoredCandidate(assessment=a, source="Bewerbungsformular", score=p, tier=t, reasons=r, missing=m,
                        consent_whatsapp=True)
    conn = store.connect()
    store.upsert(conn, c)
    key = store.candidate_key(c)
    store.set_status(conn, key, "interessiert", "test")
    return key


def _firm(name="Spedition Westfalen", phone="+49 231 000000"):
    conn = store.connect()
    store.add_company(conn, name=name, city="Dortmund", phone=phone, needs="LKW-Fahrer CE Fernverkehr")
    return conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()[0]


def test_documents_upload_flow(monkeypatch):
    key = _driver()
    c = TestClient(server.app)
    assert c.get(f"/dokumente?k={key}&t=falsch").status_code == 404
    link = deals.upload_link(key).split("/dokumente")[1]
    page = c.get("/dokumente" + link).text
    assert "Führerschein" in page and "Modul 95" in page
    st = store.doc_status(store.connect(), key, "lkw")
    assert not st["komplett"] and "Fahrerkarte" in st["fehlt"]
    files = [("lebenslauf", ("cv.pdf", b"%PDF cv", "application/pdf")),
             ("fuehrerschein", ("fs.jpg", b"jpg1", "image/jpeg")),
             ("fahrerkarte", ("fk.jpg", b"jpg2", "image/jpeg")),
             ("modul95", ("m95.jpg", b"jpg3", "image/jpeg"))]
    r = c.post("/dokumente" + link, data={"consent": "1"}, files=files)
    assert r.status_code == 200 and "komplett" in r.text
    assert store.doc_status(store.connect(), key, "lkw")["komplett"]
    assert "KOMPLETT" in store.notifications(store.connect(), 1)[0]["text"]
    assert "Fahrerkarte" in deals.doc_request_text(store.get_candidate(store.connect(), _driver("Neu Ohne", "+49 170 8880009", None)))


def test_sales_plan_call_agreement_documents_hire_invoice(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s, b, attachments)))
    key = _driver("Rita Route", "+49 170 8880002", "rita@example.org")
    cid = _firm()
    plan = deals.sales_plan()
    p = next(x for x in plan if x["firma_id"] == cid)
    assert "2.000 €" in " ".join(p["skript"]) and p["telefon"]

    msg = deals.record_call(cid, "interesse", "dispo@westfalen.example", "Herr Kraft")
    assert msg.startswith("✅ Vereinbarung")
    to, subj, body, _ = mails[-1]
    assert to == "dispo@westfalen.example" and "VERMITTLUNGSVEREINBARUNG" in body and "Herr Kraft" in body
    assert "keine Ersatz" in body and "Rita" not in body.split("VERMITTLUNGSVEREINBARUNG")[0]
    assert store.get_candidate(store.connect(), key)["status"] == "vorgestellt"
    assert all(x["firma_id"] != cid for x in deals.sales_plan())   # nicht nochmal anrufen

    cv = deals.config.DATA_DIR / "cv-test.pdf"
    cv.parent.mkdir(parents=True, exist_ok=True)
    cv.write_bytes(b"%PDF")
    store.set_state(store.connect(), f"cv:{key}", str(cv))
    assert deals.send_documents(key, cid).startswith("✅")
    assert str(cv) in mails[-1][3]

    assert "Gespräch" in deals.mark_interview(key, "Mo 10 Uhr", cid)
    today = date.today().isoformat()
    deals.mark_hired(key, cid, today)
    rev = store.revenue_month(store.connect())
    assert rev["umsatz"] >= 2000 and store.get_company(store.connect(), cid)["status"] == "kunde"
    assert "VERMITTELT" in store.notifications(store.connect(), 1)[0]["text"]

    monkeypatch.setattr(config, "UST_STATUS", "regel")
    out = deals.daily_drive()
    note = store.notifications(store.connect(), 1)[0]["text"]
    assert "Jarvis-Tagesplan" in note and "Rechnung fällig" in note and "Steuernummer" in note
    assert "2.380,00 €" in deals.invoice_text(store.placements(store.connect())[-1])
    assert out["plan"] >= 0


def test_app_api_steps(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    key = _driver("Api Fahrer", "+49 170 8880003", None)
    cid = _firm("Logistik Test", "+49 30 1111")
    c = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    v = c.get("/api/vertrieb", headers=h).json()
    assert "umsatz" in v and any(p["firma_id"] == cid for p in v["plan"])
    d = c.get(f"/api/kandidat/{key}", headers=h).json()
    assert d["dokumente"]["komplett"] is False and d["dokumente_whatsapp"].startswith("https://wa.me/49170")
    assert "nicht_erreicht" in c.post(f"/api/vertrieb/{cid}", headers=h, json={"ergebnis": "nicht_erreicht"}).json()["meldung"]
    r = c.post(f"/api/kandidat/{key}/schritt", headers=h, json={"art": "eingestellt", "firma_id": cid, "start": "2031-01-15"})
    assert r.status_code == 200 and store.revenue_month(store.connect(), "2031-01")["umsatz"] == 2000
