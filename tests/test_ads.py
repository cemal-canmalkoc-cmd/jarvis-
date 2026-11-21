"""Inserate: schreiben, auf Facebook-Seite posten, Gruppen-Text als Meldung."""
from datetime import datetime
from types import SimpleNamespace

from jarvis import ads, autopilot, config, store


def _fake_claude(monkeypatch, text="🇨🇭 Pflegekräfte gesucht! Bewerben: …/bewerbung #pflege"):
    monkeypatch.setattr(ads.brain, "create", lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]))


def test_daily_round_without_facebook(monkeypatch):
    _fake_claude(monkeypatch)
    monkeypatch.setattr(config, "META_PAGE_ID", "")
    out = ads.daily_round()
    assert out["facebook_seite"] is None and "Pflegekräfte" in out["gruppen_text"]
    assert "Inserat des Tages" in store.notifications(store.connect(), 1)[0]["text"]


def test_daily_round_posts_to_page(monkeypatch):
    _fake_claude(monkeypatch)
    monkeypatch.setattr(config, "META_PAGE_ID", "123")
    monkeypatch.setattr(config, "META_PAGE_TOKEN", "tok")
    posted = {}

    def fake_post(url, data, timeout):
        posted.update(url=url, **data)
        return SimpleNamespace(status_code=200, json=lambda: {"id": "123_456"}, text="")
    monkeypatch.setattr(ads.requests, "post", fake_post)
    out = ads.daily_round()
    assert out["facebook_seite"] == "123_456" and posted["url"].endswith("/123/feed")
    assert posted["link"].endswith("/bewerbung") and posted["access_token"] == "tok"
    assert "Facebook-Seite gepostet" in store.notifications(store.connect(), 1)[0]["text"]


def test_slots_and_prompt_rules(monkeypatch):
    monkeypatch.setattr(config, "ADS_PER_DAY", 2)
    assert ads.due_slots(datetime(2026, 11, 20, 9)) == []
    assert ads.due_slots(datetime(2026, 11, 20, 11)) == [0]
    assert ads.due_slots(datetime(2026, 11, 20, 19)) == [0, 1]
    assert "/bewerbung" in ads.AD_SYSTEM and "Keine erfundenen Lohnzahlen" in ads.AD_SYSTEM


def test_settings_from_app(monkeypatch):
    from fastapi.testclient import TestClient
    from jarvis import server
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    c = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    r = c.post("/api/einstellungen", json={"META_PAGE_ID": "999", "META_PAGE_TOKEN": "geheim1234",
                                           "SEARCH_EVERY_HOURS": "4"}, headers=h)
    assert r.status_code == 200
    assert config.META_PAGE_ID == "999" and config.SEARCH_EVERY_HOURS == 4
    overview = {s["key"]: s for s in c.get("/api/einstellungen", headers=h).json()}
    assert overview["META_PAGE_TOKEN"]["wert"] == "••••1234"
    assert c.post("/api/einstellungen", json={"ANTHROPIC_API_KEY": "x"}, headers=h).status_code == 400
    monkeypatch.setattr(config, "META_PAGE_ID", "")
    monkeypatch.setattr(config, "META_PAGE_TOKEN", "")
    monkeypatch.setattr(config, "SEARCH_EVERY_HOURS", 2)
