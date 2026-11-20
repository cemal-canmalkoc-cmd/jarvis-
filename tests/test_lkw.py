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
    monkeypatch.setattr(server, "_evaluate_form", lambda raw: seen.update(text=raw.text))
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
