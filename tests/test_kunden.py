"""Bestandskunden, Honorare und automatische Belieferung."""
from fastapi.testclient import TestClient

from jarvis import agent, config, matching, pricing, server, store, voice
from tests.test_system import add_candidate, tw  # noqa: F401


def test_no_invented_prices():
    ov = pricing.overview()
    assert set(ov) == {"Pflege", "FaGe", "Arzt", "LKW", "LKW mit ADR"}
    assert "Nenne KEINE Preise" in pricing.phone_text() or "Konditionen (nur nennen" in pricing.phone_text()


def test_set_price_via_tool_and_describe():
    msg = agent.t_preis_setzen("FaGe", "pauschal_chf", 6500, 3)
    assert "CHF 6'500 pauschal" in msg and "3 Monate Ersatzgarantie" in msg
    agent.t_preis_setzen("Arzt", "prozent_jahreslohn", 20, 6)
    assert "20 % des vereinbarten Bruttojahreslohns" in pricing.for_candidate("arzt", "Radiologie")
    assert pricing.area_for("pflege", "FaGe") == "FaGe"
    assert "20 %" in pricing.phone_text()


def test_invalid_price_rejected():
    out, err = agent.run_tool("preis_setzen", {"bereich": "Pflege", "modell": "gratis", "wert": 1})
    assert err


def test_customer_auto_delivery_once(tw, monkeypatch):  # noqa: F811
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, subj, body: mails.append((to, body)))
    cid = int(agent.t_kunde_anlegen("Spital Kunde AG", "Zürich", "hr@kunde.example", "Herr Meier",
                                    bedarf="2 Dipl. Pflegefachpersonen Akutspital").split("Firma ")[1].split(")")[0])
    _ = cid
    key = add_candidate(phone="+41 79 555 00 01", full_name="Kim Kandidatin", nursing_field="Akutspital")
    assert matching.open_customer_needs()  # Auftrag noch offen

    store.set_status(store.connect(), key, "interessiert")
    done = matching.auto_deliver()
    assert any("Kim Kandidatin" in d and "Spital Kunde AG" in d for d in done)
    to, body = next(m for m in mails if "Akutspital" in m[1])
    assert to == "hr@kunde.example" and "Herr Meier" in body and "Kooperationsvereinbarung" in body
    assert "Kim" not in body
    assert matching.auto_deliver() == []           # nie doppelt liefern
    assert any("📦 Lieferung" in m["body"] for m in tw.msgs)
    assert not any("Spital Kunde AG" in n for n in matching.open_customer_needs())


def test_non_customer_email_contains_price(tw, monkeypatch):  # noqa: F811
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, subj, body: mails.append(body))
    agent.t_preis_setzen("Pflege", "prozent_jahreslohn", 18, 3)
    conn = store.connect()
    store.add_company(conn, name="Neue Klinik", city="Bern", needs="Pflege Psychiatrie")
    cid = conn.execute("SELECT id FROM companies WHERE name='Neue Klinik'").fetchone()[0]
    store.set_company_contact(conn, cid, "jobs@neu.example", None)
    key = add_candidate(phone="+41 79 555 00 02", nursing_field="Psychiatrie")
    store.set_status(conn, key, "interessiert")
    assert matching.present(key, cid).startswith("✅")
    assert "18 % des vereinbarten Bruttojahreslohns" in mails[0]
    assert "bereits vorgestellt" in matching.present(key, cid)


def test_company_call_prompt_contains_prices(tw):  # noqa: F811
    agent.t_preis_setzen("Pflege", "prozent_jahreslohn", 18, 3)
    conn = store.connect()
    store.add_company(conn, name="Anrufklinik", city="Chur", needs="Pflege", phone="+41 81 000 00 00")
    row = conn.execute("SELECT * FROM companies WHERE name='Anrufklinik'").fetchone()
    system, greeting = voice.company_context(row)
    assert "18 %" in system and "Hansa Personal" in greeting


def test_app_lists_customers_first_with_prices(tw, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    agent.t_kunde_anlegen("AAA Kunde", "Basel", "a@b.example")
    d = TestClient(server.app).get("/api/uebersicht", headers={"Authorization": "Bearer t0k"}).json()
    assert d["firmen"][0]["status"] == "kunde" and "Pflege" in d["preise"]


def test_owner_adds_candidate_from_text(monkeypatch):
    from jarvis import pipeline
    from jarvis.models import Assessment, ScoredCandidate
    from jarvis.scoring import score

    def fake_eval(raw):
        assert raw.consent_whatsapp and "Lena" in raw.text
        a = Assessment(full_name="Lena Text", phone="+41 79 777 00 01", category="pflege",
                       nursing_field="Psychiatrie", has_diploma_certificate=True, german_level="C1",
                       recognition_status="anerkannt")
        pts, t, r, m = score(a)
        return ScoredCandidate(assessment=a, source=raw.source, score=pts, tier=t, reasons=r, missing=m,
                               consent_whatsapp=raw.consent_whatsapp)
    monkeypatch.setattr(pipeline, "evaluate", fake_eval)
    out, err = agent.run_tool("kandidat_hinzufuegen", {"angaben": "Lena Text, Pflege Psychiatrie, C1, SRK",
                                                       "whatsapp_ok": True})
    assert not err and '"tier": "A"' in out
    assert "AUSFÜHREN STATT FRAGEN" in agent.OWNER_SYSTEM
