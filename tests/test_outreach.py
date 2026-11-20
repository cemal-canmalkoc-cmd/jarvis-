"""Headhunter-Ansprache per E-Mail mit WhatsApp-Link."""
from jarvis import ads, agent, config, matching, outreach, store
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score


def _cand(email="lea@example.org", **kw):
    base = dict(full_name="Lea Lead", email=email, category="pflege", nursing_field="Psychiatrie",
                has_diploma_certificate=True, german_level="C1", recognition_status="anerkannt")
    base.update(kw)
    a = Assessment(**base)
    pts, t, r, m = score(a)
    c = ScoredCandidate(assessment=a, source="https://tutti.ch/x", score=pts, tier=t, reasons=r, missing=m)
    store.upsert(store.connect(), c)
    return c


def test_email_once_with_whatsapp_link(monkeypatch):
    monkeypatch.setattr(config, "CONTACT_WHATSAPP", "+49 176 00000000")
    monkeypatch.setattr(config, "SMTP_USER", "u@gmx.de")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "pw")
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, subj, body: mails.append((to, subj, body)))
    c = _cand()
    assert outreach.reach_out(c) == "gesendet"
    to, subj, body = mails[0]
    assert to == "lea@example.org" and "Psychiatrie" in subj
    assert "https://wa.me/4917600000000?text=" in body and "STOP" in body and "Hansa Personal" in body
    assert outreach.reach_out(c) == "schon_kontaktiert" and len(mails) == 1


def test_no_mail_without_email_or_unsuitable(monkeypatch):
    monkeypatch.setattr(config, "SMTP_USER", "u@gmx.de")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "pw")
    assert outreach.reach_out(_cand(email=None, full_name="Ohne Mail")) == "keine_email"
    assert outreach.reach_out(_cand(email="x@y.org", german_level="A2")) == "ungeeignet"


def test_contact_in_ads_and_agent(monkeypatch):
    monkeypatch.setattr(config, "CONTACT_WHATSAPP", "+49 176 00000000")
    assert "+49 176 00000000" in ads._system()
    assert "Headhunter" in agent.OWNER_SYSTEM
    keys = {s["key"] for s in store.settings_overview()}
    assert "META_TOKEN" not in keys and "SMTP_PASSWORD" in keys and "CONTACT_WHATSAPP" in keys


def test_owner_call(monkeypatch):
    from types import SimpleNamespace
    from jarvis import messaging, voice
    calls = []
    monkeypatch.setattr(messaging, "_twilio", SimpleNamespace(calls=SimpleNamespace(create=lambda **kw: calls.append(kw))))
    monkeypatch.setattr(config, "OWNER_PHONE", "")
    assert "nicht eingerichtet" in voice.call_owner("x", force=True)
    monkeypatch.setattr(config, "OWNER_PHONE", "+49 151 00000000")
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setattr(config, "TWILIO_VOICE_FROM", "+4930000000")
    assert agent.t_mich_anrufen().startswith("📞")
    assert calls[0]["to"] == "+4915100000000" and "Testanruf" in calls[0]["twiml"] and 'de-DE' in calls[0]["twiml"]


def test_smtp_autodetect_and_outlook_hint(monkeypatch):
    import smtplib
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_USER", "hansa.personal@outlook.de")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "pw")
    assert matching.smtp_host() == "smtp-mail.outlook.com"
    monkeypatch.setattr(config, "SMTP_USER", "x@gmx.de")
    assert matching.smtp_host() == "mail.gmx.net"

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"basic auth disabled")
    monkeypatch.setattr(matching.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(config, "SMTP_USER", "hansa.personal@outlook.de")
    try:
        matching.send_email("a@b.c", "s", "b")
    except RuntimeError as exc:
        assert "App-Kennwort" in str(exc)
    else:
        raise AssertionError("kein Fehler")
