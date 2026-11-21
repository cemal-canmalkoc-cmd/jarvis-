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


def test_total_budget_one_per_day_and_waits_after_five_days(monkeypatch):
    from jarvis import budget as b
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 1.0)
    monkeypatch.setattr(config, "CHAT_MAX_USD", 0.20)
    conn = store.connect()
    store.set_state(conn, "auto_until", date.today().isoformat())
    store.set_state(conn, f"spend:{date.today()}", "0.79")
    store.set_state(conn, f"chat_spend:{date.today()}", "0")
    assert not b.auto_allowed(0.02)                 # 0,20 $ bleiben für Gespräche reserviert
    assert b.chat_allowed(0.01)
    store.set_state(conn, f"spend:{date.today()}", "0.999")
    assert not b.chat_allowed(0.01)                 # Gesamtgrenze 1,00 $
    store.set_state(conn, f"spend:{date.today()}", "0")
    store.set_state(conn, "auto_until", (date.today() - timedelta(days=1)).isoformat())
    assert not b.auto_allowed(0.01) and not b.chat_allowed(0.001)   # wartet auf „Weiter“
    b.autonomy_continue()


def test_defaults_applied_once_after_update():
    from jarvis import budget as b
    conn = store.connect()
    store.set_state(conn, "autonomy_version", "")
    store.save_setting(conn, "DAILY_BUDGET_USD", "0")
    b.ensure_defaults()
    assert config.DAILY_BUDGET_USD == 1.0 and config.CHAT_MAX_USD == 0.20 and config.AUTO_APPLY is True
    assert b.autonomy_until() == date.today() + timedelta(days=4)
    store.save_setting(conn, "CHAT_MAX_USD", "0.1")
    b.ensure_defaults()                              # zweites Mal ändert nichts
    assert config.CHAT_MAX_USD == 0.1
    store.save_setting(conn, "CHAT_MAX_USD", "0.20")


def test_outlook_uses_microsoft_login_instead_of_password(monkeypatch):
    import smtplib
    from jarvis import msauth
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_USER", "hansa.personal@outlook.de")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(config, "MS_CLIENT_ID", "00000000-1111-2222-3333-444444444444")
    store.set_state(store.connect(), "ms_refresh_token", "")
    assert not matching.mail_ready()                          # ohne Anmeldung kein Versand
    store.set_state(store.connect(), "ms_refresh_token", "rt-123")
    monkeypatch.setattr(msauth, "_cache", {"token": "at-xyz", "exp": 9e12})
    assert matching.mail_ready() and inbox.imap_host() == "outlook.office365.com"
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout): calls.append(("host", host))
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def ehlo(self): pass
        def auth(self, mech, obj, initial_response_ok=True): calls.append((mech, obj()))
        def login(self, *a): calls.append(("login",))
        def send_message(self, m): calls.append(("sent", m["To"]))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    matching.send_email("x@example.org", "Test", "Hallo")
    assert ("host", "smtp-mail.outlook.com") in calls and ("login",) not in calls
    mech, s = next(c for c in calls if c[0] == "XOAUTH2")
    assert "user=hansa.personal@outlook.de" in s and "Bearer at-xyz" in s
    assert ("sent", "x@example.org") in calls
    store.set_state(store.connect(), "ms_refresh_token", "")


def test_daily_approval_asks_first_and_catches_up_morning(monkeypatch):
    from jarvis import budget as b
    monkeypatch.setattr(config, "ASK_DAILY", True)
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 1.0)
    conn = store.connect()
    store.set_state(conn, f"approved:{date.today()}", "")
    store.set_state(conn, f"spend:{date.today()}", "0")
    store.set_state(conn, f"chat_spend:{date.today()}", "0")
    assert not b.auto_allowed(0.01) and not b.chat_allowed(0.001)      # ohne Ja: nichts ausgeben
    store.set_state(conn, "morning", date.today().isoformat())
    store.set_state(conn, f"morning_skipped:{date.today()}", "1")
    assert "heute selbstständig" in b.autonomy_continue()               # Ja in der App
    assert b.auto_allowed(0.01) and b.chat_allowed(0.001)
    assert store.get_state(conn, "morning") == ""                        # Morgensuche wird nachgeholt
    store.set_state(conn, f"approved:{date.today()}", "")


def test_team_shows_departments_and_blockers(monkeypatch):
    from jarvis import team
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "OUTBOX", False)
    t = {m["rolle"].split(" ")[0]: m for m in team.status()}
    assert {"Sourcing", "Recruiting", "Vertrieb", "Disposition", "Marketing", "Backoffice"} <= set(t)
    assert not t["Vertrieb"]["ok"] and "E-Mail" in t["Vertrieb"]["problem"]
    assert "Dein Jarvis-Team" in team.summary_text()



def test_outbox_when_no_mailbox(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "OUTBOX", True)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0k")
    matching.send_email("dispo@firma.example", "Bewerbung: CE-Fahrer", "Guten Tag …", attachments=["/x/cv.pdf"])
    matching.send_email("dispo@firma.example", "Bewerbung: CE-Fahrer", "Guten Tag …")   # kein Duplikat
    c = TestClient(server.app)
    h = {"Authorization": "Bearer t0k"}
    mails = [m for m in c.get("/api/postausgang", headers=h).json()["mails"] if m["to_addr"] == "dispo@firma.example"]
    assert len(mails) == 1 and mails[0]["mailto"].startswith("mailto:dispo@firma.example?subject=")
    assert "cv.pdf" in mails[0]["note"]
    c.post(f"/api/postausgang/{mails[0]['id']}/gesendet", headers=h)
    assert not [m for m in c.get("/api/postausgang", headers=h).json()["mails"] if m["to_addr"] == "dispo@firma.example"]


def test_outbox_flushes_once_mailbox_connected(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "OUTBOX", True)
    matching.send_email("flush@firma.example", "Flush-Test", "Text")
    sent = []
    monkeypatch.setattr(matching, "mail_ready", lambda: True)
    real = matching.send_email
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: sent.append(to))
    assert matching.flush_outbox() >= 1 and "flush@firma.example" in sent
    assert not [m for m in store.outbox(store.connect()) if m["to_addr"] == "flush@firma.example"]


def test_whatsapp_number_from_email_reply_is_saved():
    key = _driver("Mail Fahrer", None, "mailfahrer@example.org")
    convo._save_whatsapp(key, "0176 55512345")
    row = store.get_candidate(store.connect(), key)
    c = store.load(row)
    assert row["phone"] == "0176 55512345" and c.whatsapp_link.startswith("https://wa.me/4917655512345")
