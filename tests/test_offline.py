"""Tests ohne API-Aufruf: Bewertung, WhatsApp-Links, Report, Speicher."""
from jarvis.models import Assessment, ScoredCandidate
from jarvis.scoring import score
from jarvis.whatsapp import build_link, build_message, normalize_phone


def nurse(**kw):
    base = dict(full_name="Anna Muster", phone="079 123 45 67", category="pflege",
                nursing_field="Psychiatrie", has_diploma_certificate=True, german_level="B2",
                recognition_status="anerkannt", currently_in_switzerland=True)
    base.update(kw)
    return Assessment(**base)


def test_nurse_with_srk_is_A():
    pts, tier, reasons, _ = score(nurse())
    assert tier == "A" and pts >= 75
    assert any("SRK" in r for r in reasons)


def test_nurse_precheck_is_A():
    assert score(nurse(recognition_status="positiver_precheck"))[1] == "A"


def test_nurse_below_b2_is_knocked_out():
    assert score(nurse(german_level="B1"))[1] == "X"


def test_nurse_without_diploma_is_knocked_out():
    assert score(nurse(has_diploma_certificate=False))[1] == "X"


def test_doctor_mebeko_wanted_specialty():
    a = Assessment(full_name="Dr. Max Beispiel", phone="+49 170 1234567", category="arzt",
                   physician_specialty="Anästhesie", german_level="C1",
                   recognition_status="anerkannt")
    assert score(a)[1] == "A"


def test_doctor_unwanted_specialty_lower():
    a = Assessment(full_name="Dr. X", category="arzt", physician_specialty="Dermatologie",
                   german_level="C1", recognition_status="anerkannt")
    assert score(a)[0] < score(a.model_copy(update={"physician_specialty": "Radiologie"}))[0]


def test_phone_normalization():
    assert normalize_phone("079 123 45 67") == "41791234567"
    assert normalize_phone("+49 170 1234567") == "491701234567"
    assert normalize_phone("0049 170 1234567") == "491701234567"
    assert normalize_phone("123") is None


def test_whatsapp_link():
    a = nurse()
    msg = build_message(a)
    assert "Grüezi Anna" in msg and "SRK" in msg
    link = build_link(a.phone, msg)
    assert link.startswith("https://wa.me/41791234567?text=")


def test_report_and_store(tmp_path, monkeypatch):
    from jarvis import report, store
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "db.sqlite3")
    a = nurse()
    pts, tier, reasons, missing = score(a)
    c = ScoredCandidate(assessment=a, source="test", score=pts, tier=tier, reasons=reasons,
                        missing=missing, whatsapp_link=build_link(a.phone, build_message(a)))
    conn = store.connect()
    assert store.upsert(conn, c) is True
    assert store.upsert(conn, c) is False  # Dublette
    short = store.todays_shortlist(conn, 10)
    assert len(short) == 1
    h, _ = report.write(short)
    assert "wa.me" in h.read_text()
