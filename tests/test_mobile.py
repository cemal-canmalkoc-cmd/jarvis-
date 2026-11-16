"""iPhone-App und Siri-Schnittstelle."""
import time

from fastapi.testclient import TestClient

from jarvis import agent, config, server
from tests.test_system import add_candidate, tw  # noqa: F401  (Fixture)


def client(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "geheim-123")
    return TestClient(server.app)


def test_app_requires_login(monkeypatch):
    c = client(monkeypatch)
    r = c.get("/app", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/login"
    assert c.get("/api/uebersicht").status_code == 401


def test_wrong_code_rejected(monkeypatch):
    c = client(monkeypatch)
    r = c.post("/app/login", data={"token": "falsch"}, follow_redirects=False)
    assert "fehler=1" in r.headers["location"]
    assert c.get("/api/uebersicht").status_code == 401


def test_login_and_dashboard(monkeypatch, tw):  # noqa: F811
    key = add_candidate(phone="+41 79 333 00 01", full_name="Sara App")
    c = client(monkeypatch)
    r = c.post("/app/login", data={"token": "geheim-123"}, follow_redirects=False)
    assert r.status_code == 303 and "jarvis_session" in r.headers["set-cookie"]
    page = c.get("/app")
    assert page.status_code == 200 and "apple-touch-icon" in page.text
    d = c.get("/api/uebersicht").json()
    assert d["stats"]["ziel"] == config.DAILY_TARGET
    assert any(k["id"] == key and k["name"] == "Sara App" for k in d["kandidaten"])
    assert c.get(f"/api/kandidat/{key}").json()["telefon"] == "+41 79 333 00 01"
    assert c.post(f"/api/kandidat/{key}/status", json={"status": "interessiert"}).status_code == 200
    assert c.post(f"/api/kandidat/{key}/status", json={"status": "quatsch"}).status_code == 400
    msg = c.post(f"/api/kandidat/{key}/anrufen").json()["meldung"]
    assert "Rufe Sara App an" in msg


def test_manifest_and_icon(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/app/manifest.webmanifest").json()["display"] == "standalone"
    r = c.get("/app/icon-180.png")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_siri_bearer_waits_for_answer(monkeypatch):
    monkeypatch.setattr(agent, "handle_owner", lambda t: f"Erledigt: {t}")
    c = client(monkeypatch)
    r = c.post("/api/befehl", json={"text": "Tagesbericht", "warten": 10},
               headers={"Authorization": "Bearer geheim-123"})
    assert r.json() == {"job": r.json()["job"], "status": "fertig", "antwort": "Erledigt: Tagesbericht"}
    assert c.post("/api/befehl", json={"text": "x"},
                  headers={"Authorization": "Bearer falsch"}).status_code == 401


def test_slow_job_reports_via_whatsapp(monkeypatch, tw):  # noqa: F811
    def slow(t):
        time.sleep(1.5)
        return "Fertig nach langer Suche"
    monkeypatch.setattr(agent, "handle_owner", slow)
    c = client(monkeypatch)
    r = c.post("/api/befehl", json={"text": "Starte die Web-Suche", "warten": 0.5},
               headers={"Authorization": "Bearer geheim-123"}).json()
    assert r["status"] == "läuft" and "WhatsApp" in r["antwort"]
    for _ in range(40):
        if any("Fertig nach langer Suche" in m.get("body", "") for m in tw.msgs):
            break
        time.sleep(0.1)
    assert any("Fertig nach langer Suche" in m.get("body", "") for m in tw.msgs)
    st = c.get(f"/api/befehl/{r['job']}", headers={"Authorization": "Bearer geheim-123"}).json()
    assert st["status"] == "fertig"
