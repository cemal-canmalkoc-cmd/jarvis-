"""Selbstständiger Betrieb: KI-Chat, Postfach, Firma will Kandidat → verbinden → Einstellung."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from jarvis import budget, config, convo, inbox, matching, pipeline, server, store
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score
from tests.test_deals import _driver, _firm


def _fake_eval(name="Chat Fahrer", email="chat@example.org"):
    def ev(raw):
        a = Assessment(full_name=name, phone="+49 170 4440001", email=email, category="lkw", driving_license="CE",
                       driver_card=True, code95=True, traffic_type="Fernverkehr", years_experience=4,
                       german_level="muttersprache", current_location="44137 Dortmund", summary="aus Chat")
        p, t, r, m = score(a)
        return ScoredCandidate(assessment=a, source=raw.source, score=p, tier=t, reasons=r, missing=m,
                               consent_whatsapp=True, consent_call=True)
    return ev


def test_wa_links_lead_to_ai_chat(monkeypatch):
    monkeypatch.setattr(config, "CHAT_FIRST", True)
    c = TestClient(server.app)
    r = c.get("/wa?b=lkw&q=mail", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/chat?b=lkw")
    assert c.get("/wa?b=firma", follow_redirects=False).headers["location"] == "/firmen"
    page = c.get("/chat?b=lkw").text
    assert "KI-Assistent" in page and "Datenschutz" in page
    assert "Anthropic" in c.get("/datenschutz").text


def test_web_chat_qualifies_and_creates_candidate(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s)))
    monkeypatch.setattr(pipeline, "evaluate", _fake_eval())
    monkeypatch.setattr(config, "SMTP_USER", "hansa@example.org")
    answers = iter([
        {"antwort": "Hast du die Fahrerkarte?", "status": "offen", "einwilligung": False, "profil": "CE", "fertig": False},
        {"antwort": "Super, danke!", "status": "interessiert", "einwilligung": True,
         "profil": "Chat Fahrer, CE, Fahrerkarte, Dortmund, chat@example.org", "fertig": True},
    ])
    monkeypatch.setattr(convo, "_ask", lambda system, schema, msgs: next(answers))
    c = TestClient(server.app)
    sid = "ab12cd34ef56ab12cd34ef56"
    assert c.post("/chat/nachricht", json={"sid": sid, "text": "Hallo, CE", "b": "lkw"}).json()["antwort"].startswith("Hast")
    r = c.post("/chat/nachricht", json={"sid": sid, "text": "Ja, gerne vorstellen", "b": "lkw"}).json()
    assert "Super" in r["antwort"] and "/dokumente?" in r["antwort"]
    conv = store.get_convo(store.connect(), f"web:{sid}")
    row = store.get_candidate(store.connect(), conv["cand_key"])
    assert row["status"] == "interessiert"
    assert any("Unterlagen" in s for _, s in mails)          # Dokumente automatisch angefordert
    assert c.post("/chat/nachricht", json={"sid": "x", "text": "hi"}).status_code == 400


def test_chat_without_budget_answers_politely(monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_USD", 0.0)
    reply = convo.candidate_turn("web:00112233445566778899", "Hallo", "Web-Chat")
    assert reply == convo.OFFLINE_REPLY


def test_five_day_approval_window(monkeypatch):
    conn = store.connect()
    store.set_state(conn, "auto_until", (date.today() - timedelta(days=1)).isoformat())
    assert not budget.autonomy_active() and not budget.chat_allowed()
    assert "selbstständig weiter" in budget.autonomy_continue()
    assert budget.autonomy_active() and budget.autonomy_until() == date.today() + timedelta(days=config.AUTO_DAYS - 1)


def test_company_reply_yes_connects_and_hire_is_recorded(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s, b)))
    key = _driver("Verbind Fahrer", "+49 170 4440002", "verbind@example.org")
    cid = _firm("Spedition Antwort", "+49 231 4440")
    store.set_company_contact(store.connect(), cid, "dispo@antwort-spedition.example", "Herr Dispo")
    store.record_presentation(store.connect(), key, cid, "bewerbung-anzeige")
    answers = iter([
        {"absicht": "unterlagen", "antwort": "Gerne, Unterlagen kommen.", "startdatum": "", "an_inhaber": ""},
        {"absicht": "eingestellt", "antwort": "Glückwunsch!", "startdatum": "2026-12-01", "an_inhaber": ""},
    ])
    monkeypatch.setattr(convo, "_ask", lambda system, schema, msgs: next(answers))
    info = inbox.handle("dispo@antwort-spedition.example", "Re: Bewerbung", "Ja, schicken Sie bitte alles", [])
    assert "verbunden" in info
    assert store.get_candidate(store.connect(), key)["status"] == "gespraech"
    tos = [m[0] for m in mails]
    assert "verbind@example.org" in tos and "dispo@antwort-spedition.example" in tos
    # andere Adresse derselben Firmen-Domain wird erkannt
    info = inbox.handle("chef@antwort-spedition.example", "Re: Rückfrage", "Eingestellt ab 1.12.", [])
    assert "eingestellt" in info
    assert store.get_candidate(store.connect(), key)["status"] == "vermittelt"
    assert not any("Rechnung" in m[1] for m in mails)        # Rechnung nur nach Genehmigung


def test_followup_after_a_week(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s)))
    key = _driver("Nachfrage Fahrer", "+49 170 4440003", None)
    cid = _firm("Spedition Nachfrage", "+49 231 4441")
    store.set_company_contact(store.connect(), cid, "info@nachfrage.example", None)
    conn = store.connect()
    store.set_status(conn, key, "gespraech", "test")
    store.set_state(conn, f"intro_at:{key}", (date.today() - timedelta(days=8)).isoformat())
    store.set_state(conn, f"intro_firm:{key}", str(cid))
    assert convo.followups() and mails[-1][0] == "info@nachfrage.example"
    assert not convo.followups()                                 # nur einmal


def test_inbox_ignores_autoreplies_and_unknown():
    assert inbox.handle("noreply@shop.example", "Ihre Bestellung", "Danke", []) is None
    assert inbox.handle("fremd@example.org", "Hallo", "Werbung", []) is None
    assert inbox.imap_host() in ("", "imap.gmx.net", "outlook.office365.com") or config.IMAP_HOST
