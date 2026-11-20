"""Zweiter Bereich: LKW-Fahrer in Deutschland."""
from fastapi.testclient import TestClient

from jarvis import ads, brain, companies, config, matching, outreach, pipeline, server, store
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score
from jarvis.whatsapp import role_phrase


def driver(**kw):
    base = dict(full_name="Tom Truck", phone="+49 170 7770001", category="lkw", driving_license="CE",
                driver_card=True, code95=True, adr=True, years_experience=6, traffic_type="Fernverkehr",
                german_level="muttersprache", current_location="44135 Dortmund")
    base.update(kw)
    return Assessment(**base)


def test_scoring_and_role():
    pts, tier, reasons, missing = score(driver())
    assert tier == "A" and any("CE" in r for r in reasons)
    assert role_phrase(driver()) == "Berufskraftfahrer/in (CE)"
    assert score(driver(driving_license="B"))[1] == "X"
    p2, t2, r2, m2 = score(driver(code95=None, driver_card=None))
    assert "Modul 95 klären" in m2 and p2 < pts


def test_anonymous_profile_hides_identity():
    a = driver()
    pts, tier, r, m = score(a)
    c = ScoredCandidate(assessment=a, source="x", score=pts, tier=tier, reasons=r, missing=m)
    store.upsert(store.connect(), c)
    row = store.get_candidate(store.connect(), store.candidate_key(c))
    prof = matching.anonymous_profile(row)
    assert "Führerschein: CE" in prof and "Modul 95: ja" in prof and "PLZ 44xxx" in prof
    assert "Tom" not in prof and "Dortmund" not in prof and "+49" not in prof


def test_lkw_texts():
    a = driver(email="tom@example.org")
    pts, tier, r, m = score(a)
    c = ScoredCandidate(assessment=a, source="https://kleinanzeigen.de/x", score=pts, tier=tier, reasons=r, missing=m)
    subj, body = outreach.build_email(c)
    assert "Fahrerstellen" in subj and "Speditionen" in body and "Schweiz" not in body
    assert "bereich=lkw" in outreach.portal_message(c)
    assert brain.is_lkw_focus("LKW: Fahrer CE") and not brain.is_lkw_focus("Pflege")
    assert "Berufskraftfahrer" in brain.EXTRACT_SYSTEM and "code95" in brain.ASSESSMENT_SCHEMA["required"]
    assert "Speditionen" in companies.LKW_SYSTEM
    assert "lkw" in ads._system(True).lower()
    assert any(f.startswith("LKW:") for f in pipeline.default_web_focuses())


def test_driver_form(monkeypatch):
    seen = {}
    monkeypatch.setattr(server, "_evaluate_form", lambda raw, cv=None: seen.update(text=raw.text))
    c = TestClient(server.app)
    page = c.get("/bewerbung?bereich=lkw").text
    assert "LKW-Fahrer gesucht" in page and 'name="fuehrerschein"' in page
    r = c.post("/bewerbung", data={"name": "Tom Truck", "phone": "+49 170 7770002", "wohnort": "44135 Dortmund",
                                   "bereich": "LKW-Fahrer Fernverkehr", "fuehrerschein": "CE", "fahrerkarte": "ja",
                                   "modul95": "ja", "adr": "nein", "consent_data": "1"})
    assert r.status_code == 200 and "Führerscheinklasse: CE" in seen["text"]


def test_lkw_default_price():
    from jarvis import pricing
    txt = pricing.for_candidate("lkw", None)
    assert txt.startswith("2.000 € pauschal (zzgl. gesetzlicher MwSt., sofern anfallend)") and "Garantie" not in txt
    assert pricing.overview()["LKW"] == txt


def test_ust_status(monkeypatch):
    from jarvis import pricing
    monkeypatch.setattr(config, "UST_STATUS", "kleinunternehmer")
    assert "§ 19 UStG keine Umsatzsteuer" in pricing.for_candidate("lkw", None)
    monkeypatch.setattr(config, "UST_STATUS", "regel")
    assert "2.000 € netto pauschal (zzgl. 19 % MwSt.)" in pricing.for_candidate("lkw", None)



def test_adr_price():
    from jarvis import pricing
    assert pricing.for_candidate("lkw", None, adr=True).startswith("3.000 € pauschal")
    assert pricing.for_candidate("lkw", None, adr=False).startswith("2.000 € pauschal")
    assert "LKW mit ADR" in pricing.overview()


def test_app_shows_readable_unknown_candidates(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    a = driver(full_name="unbekannt", phone=None, current_location="44135 Dortmund", summary="Fahrer Dortmund xyz")
    p, t, r, m = score(a)
    c = ScoredCandidate(assessment=a, source="https://www.kleinanzeigen.de/s-anzeige/123", score=p, tier=t,
                        reasons=r, missing=m)
    store.upsert(store.connect(), c)
    key = store.candidate_key(c)
    cl = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    item = next(k for k in cl.get("/api/uebersicht", headers=h).json()["kandidaten"] if k["id"] == key)
    assert item["name"] == "Berufskraftfahrer/in (CE) · 44135 Dortmund"
    assert "Modul 95 ✓" in item["details"] and "ADR ✓" in item["details"]
    d = cl.get(f"/api/kandidat/{key}", headers=h).json()
    assert d["quelle"].startswith("https://www.kleinanzeigen.de") and "Speditionen" in d["nachricht"]
    assert cl.post(f"/api/kandidat/{key}/loeschen", headers=h).status_code == 200
    assert store.get_candidate(store.connect(), key) is None


def test_applicant_becomes_interested_with_cv_and_firms(monkeypatch, tmp_path):
    from jarvis import messaging
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    a = driver(full_name="Bea Bewerber", phone="+49 170 7770099")
    p, t, r, m = score(a)
    monkeypatch.setattr(pipeline, "evaluate", lambda raw: ScoredCandidate(
        assessment=a, source="Bewerbungsformular", score=p, tier=t, reasons=r, missing=m, consent_whatsapp=True))
    conn = store.connect()
    store.add_company(conn, name="Spedition Ruhr", city="Dortmund", needs="LKW-Fahrer CE Fernverkehr")
    cv = tmp_path / "20261120-cv.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    server._evaluate_form(server.sources.RawProfile(source="Bewerbungsformular", text="x"), str(cv))
    key = store.candidate_key(ScoredCandidate(assessment=a, source="Bewerbungsformular", score=p, tier=t,
                                              reasons=r, missing=m))
    assert store.get_candidate(conn, key)["status"] == "interessiert"
    note = store.notifications(conn, 1)[0]["text"]
    assert "NEUER BEWERBER: Bea Bewerber" in note and "Passende Firmen" in note and "liegt vor" in note
    cl = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    assert cl.get(f"/api/kandidat/{key}", headers=h).json()["lebenslauf"] is True
    assert cl.get(f"/api/kandidat/{key}/lebenslauf", headers=h).content.startswith(b"%PDF")


def test_lkw_focus_detected_without_prefix():
    from jarvis import brain
    assert brain.is_lkw_focus("Berufskraftfahrer C/CE, Fahrerkarte, Modul 95, Deutschland")
    assert brain.is_lkw_focus("LKW: Fahrer ADR")
    assert not brain.is_lkw_focus("Pflegefachfrau Psychiatrie Zürich")
    assert not brain.is_lkw_focus("Arzt Anästhesie Bern")


def test_invented_ad_links_are_replaced_by_real_search_results():
    from jarvis import brain
    seen = ["https://www.kleinanzeigen.de/s-jobs/lkw-fahrer-sucht-arbeit/k0c102",
            "https://www.kleinanzeigen.de/s-anzeige/ce-fahrer-sucht-arbeit/2876543210-107-1234",
            "https://www.quoka.de/stellengesuche/kraftfahrer.html"]
    assert brain.real_url(seen[1], seen) == seen[1]                       # echter Link bleibt
    fake = "https://www.kleinanzeigen.de/s-anzeige/erfunden/999-107-1"
    assert brain.real_url(fake, seen) in seen[:2]                         # erfunden → echter Treffer
    assert brain.real_url("https://erfunden.example/x", seen) == seen[0]


def test_german_mobile_numbers_get_49():
    from jarvis.whatsapp import normalize_phone
    assert normalize_phone("01556 2669587") == "4915562669587"
    assert normalize_phone("0176 12345678") == "4917612345678"
    assert normalize_phone("079 123 45 67") == "41791234567"
    assert normalize_phone("0231 123456", "49") == "49231123456"
