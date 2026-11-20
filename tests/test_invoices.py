"""PDF-Rechnungen mit Pflichtangaben, Nummernkreis, Versand."""
import io
from datetime import date

from pypdf import PdfReader

from jarvis import config, deals, invoices, matching, store
from tests.test_deals import _driver, _firm


def _setup(monkeypatch, ust="regel"):
    monkeypatch.setattr(config, "FIRMA_ADRESSE", "Musterweg 1, 44135 Dortmund")
    monkeypatch.setattr(config, "STEUERNUMMER", "315/5555/1234")
    monkeypatch.setattr(config, "IBAN", "DE00 1234 5678 9000 0000 00")
    monkeypatch.setattr(config, "UST_STATUS", ust)
    key = _driver(f"Rechnung {ust}", f"+49 170 66600{1 if ust == 'regel' else 2}", None)
    cid = _firm(f"Kunde {ust}", "+49 231 777")
    store.set_company_contact(store.connect(), cid, f"buchhaltung@{ust}.example", "Frau Zahl")
    deals.mark_hired(key, cid, date.today().isoformat())
    return next(p for p in store.placements(store.connect()) if p["cand_key"] == key)


def test_blocked_without_business_data(monkeypatch):
    monkeypatch.setattr(config, "FIRMA_ADRESSE", "")
    assert any("Geschäftsadresse" in m for m in invoices.missing_business_data())


def test_pdf_has_mandatory_fields_and_sends(monkeypatch):
    mails = []
    monkeypatch.setattr(matching, "send_email", lambda to, s, b, attachments=None: mails.append((to, s, attachments)))
    p = _setup(monkeypatch, "regel")
    assert "Rechnungsadresse" in invoices.send_invoice(p["id"])          # Firmenadresse fehlt noch
    store.set_company_address(store.connect(), p["company_id"], "Logistikstr. 5, 44137 Dortmund")
    msg = invoices.send_invoice(p["id"])
    assert msg.startswith("✅ Rechnung RE-") and "2.380,00 €" in msg
    to, subj, att = mails[-1]
    assert to == "buchhaltung@regel.example" and att and att[0].endswith(".pdf")
    text = "".join(pg.extract_text() for pg in PdfReader(att[0]).pages)
    for must in ("Musterweg 1", "315/5555/1234", "DE00 1234", "Logistikstr. 5", "19 % Umsatzsteuer",
                 "2.380,00 €", "Rechnungsdatum", "Leistungsdatum", "Personalvermittlung"):
        assert must in text, must
    assert next(x for x in store.placements(store.connect()) if x["id"] == p["id"])["status"] == "rechnung"


def test_kleinunternehmer_and_numbering(monkeypatch):
    monkeypatch.setattr(matching, "send_email", lambda *a, **k: None)
    p = _setup(monkeypatch, "kleinunternehmer")
    store.set_company_address(store.connect(), p["company_id"], "Weg 2, 10115 Berlin")
    path, number, gross = invoices.build_pdf(p)
    text = "".join(pg.extract_text() for pg in PdfReader(str(path)).pages)
    assert "§ 19 UStG" in text and gross == 2000.0 and "Umsatzsteuer berechnet" in text
    path2, number2, _ = invoices.build_pdf(p)
    assert number2 == number                                           # gleiche Vermittlung → gleiche Nummer
    n1 = int(number.split("-")[-1])
    assert invoices.next_number().endswith(f"{n1 + 1:03d}")
