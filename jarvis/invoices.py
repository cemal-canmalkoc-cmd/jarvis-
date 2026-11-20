"""Rechnungen: PDF mit allen Pflichtangaben (§ 14 UStG), fortlaufende Nummer, Versand per E-Mail.

Pflichtangaben: Name/Anschrift beider Seiten, Steuernummer oder USt-IdNr., Rechnungsdatum,
fortlaufende Rechnungsnummer, Leistung + Leistungsdatum, Entgelt, Steuersatz/-betrag bzw.
Hinweis auf § 19 UStG (Kleinunternehmer). Fehlt etwas, verschickt Jarvis NICHT, sondern meldet es.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from . import config, store
from .whatsapp import role_phrase


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def missing_business_data() -> list[str]:
    need = {"FIRMA_ADRESSE": "deine Geschäftsadresse", "STEUERNUMMER": "Steuernummer oder USt-IdNr.",
            "IBAN": "IBAN für die Zahlung"}
    out = [label for key, label in need.items() if not (getattr(config, key, "") or "").strip()]
    if (config.UST_STATUS or "unklar").lower().startswith("unklar"):
        out.append("Umsatzsteuer-Status (kleinunternehmer oder regel)")
    return out


def next_number() -> str:
    conn = store.connect()
    year = date.today().year
    key = f"invoice_seq:{year}"
    n = int(store.get_state(conn, key) or 0) + 1
    store.set_state(conn, key, str(n))
    return f"RE-{year}-{n:03d}"


def ensure_reportlab() -> bool:
    """Installiert das PDF-Paket beim ersten Bedarf nach (ältere Server-Images haben es noch nicht)."""
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "reportlab"],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False
        import importlib
        importlib.invalidate_caches()
        try:
            import reportlab  # noqa: F401,F811
            return True
        except ImportError:
            return False


def build_pdf(p: dict) -> tuple[Path, str, float]:
    """Erstellt die Rechnung als PDF. Gibt (Pfad, Rechnungsnummer, Bruttobetrag) zurück."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    conn = store.connect()
    row = store.get_candidate(conn, p["cand_key"])
    firm = store.get_company(conn, p["company_id"]) if p["company_id"] else None
    a = store.load(row).assessment if row else None
    number = store.get_state(conn, f"invoice_no:{p['id']}") or next_number()
    store.set_state(conn, f"invoice_no:{p['id']}", number)
    fee = float(p["fee"] or 0)
    klein = (config.UST_STATUS or "").lower().startswith("klein")
    tax = 0.0 if klein else round(fee * 0.19, 2)
    gross = fee + tax

    folder = config.DATA_DIR / "rechnungen"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{number}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 25 * mm

    def line(text: str, size: int = 10, bold: bool = False, x: float = 20 * mm, dy: float = 5.5 * mm):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, text)
        y -= dy

    line(f"{config.RECRUITER_NAME} – {config.AGENCY_NAME}", 9)
    for part in (config.FIRMA_ADRESSE or "").split(","):
        line(part.strip(), 9, dy=4.5 * mm)
    y -= 8 * mm
    line(firm["name"] if firm else "", 11, True)
    if firm and firm["contact_name"]:
        line(f"z. Hd. {firm['contact_name']}")
    for part in ((firm["address"] if firm and firm["address"] else (firm["city"] if firm else "")) or "").split(","):
        line(part.strip())
    y -= 10 * mm
    line(f"Rechnung {number}", 16, True, dy=9 * mm)
    line(f"Rechnungsdatum: {date.today():%d.%m.%Y}")
    line(f"Leistungsdatum (Arbeitsantritt): {date.fromisoformat(p['start_date']):%d.%m.%Y}")
    y -= 6 * mm
    line("Leistung", 10, True)
    line(f"Personalvermittlung – Erfolgshonorar für die Vermittlung von")
    line(f"{a.full_name if a else ''} ({role_phrase(a) if a else ''})")
    y -= 4 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "Honorar (netto)" if not klein else "Honorar")
    c.drawRightString(w - 20 * mm, y, eur(fee))
    y -= 6 * mm
    if not klein:
        c.drawString(20 * mm, y, "zzgl. 19 % Umsatzsteuer")
        c.drawRightString(w - 20 * mm, y, eur(tax))
        y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Gesamtbetrag")
    c.drawRightString(w - 20 * mm, y, eur(gross))
    y -= 10 * mm
    if klein:
        line("Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung).", 9)
    due = date.today() + timedelta(days=14)
    line(f"Zahlbar ohne Abzug bis {due:%d.%m.%Y} auf folgendes Konto:", 10)
    line(f"IBAN: {config.IBAN}" + (f"  ·  {config.BANK}" if config.BANK else ""), 10)
    line(f"Verwendungszweck: {number}", 10)
    y -= 6 * mm
    line(f"Steuernummer/USt-IdNr.: {config.STEUERNUMMER}", 9)
    line("Vielen Dank für die Zusammenarbeit!", 10)
    c.showPage()
    c.save()
    return path, number, gross


def send_invoice(pid: int) -> str:
    from .matching import send_email
    conn = store.connect()
    p = next((x for x in store.placements(conn) if x["id"] == pid), None)
    if not p:
        return "Vermittlung nicht gefunden."
    missing = missing_business_data()
    if missing:
        return "Rechnung nicht möglich – unter ⚙️ fehlt noch: " + ", ".join(missing)
    firm = store.get_company(conn, p["company_id"]) if p["company_id"] else None
    if not firm or not firm["email"]:
        return "Für diese Vermittlung ist keine Firma mit E-Mail hinterlegt."
    if not firm["address"]:
        return f"Für {firm['name']} fehlt die vollständige Rechnungsadresse (App → Firma → Adresse)."
    if not ensure_reportlab():
        return "PDF-Baustein konnte nicht installiert werden – bitte in der App '⬇️ Jarvis aktualisieren' drücken."
    path, number, gross = build_pdf(p)
    send_email(firm["email"], f"Rechnung {number} – {config.AGENCY_NAME}",
               f"Guten Tag{' ' + firm['contact_name'] if firm['contact_name'] else ''},\n\nvielen Dank für die "
               f"Zusammenarbeit. Anbei erhalten Sie unsere Rechnung {number} über {eur(gross)} für die "
               f"erfolgreiche Vermittlung (Arbeitsantritt {date.fromisoformat(p['start_date']):%d.%m.%Y}).\n\n"
               f"Freundliche Grüsse\n{config.RECRUITER_NAME}\n{config.AGENCY_NAME}", attachments=[str(path)])
    store.set_placement_status(conn, pid, "rechnung")
    store.set_state(conn, f"invoice_sent:{pid}", date.today().isoformat())
    return f"✅ Rechnung {number} über {eur(gross)} an {firm['name']} gesendet."
