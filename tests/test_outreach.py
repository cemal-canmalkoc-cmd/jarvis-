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
