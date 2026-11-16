#!/usr/bin/env python3
"""
Baut die fertige Agentur-Website (kostenlos, ohne Server) in den Ordner  kostenlos/fertig/
Danach den Ordner 'fertig' auf https://app.netlify.com/drop ziehen -> sofort online.

  1. kostenlos/daten.example.json -> kostenlos/daten.json kopieren und ausfuellen
  2. python kostenlos/website_bauen.py
"""
import json
import re
import sys
from html import escape
from pathlib import Path

HIER = Path(__file__).resolve().parent
QUELLE = HIER.parent / "website" / "index.html"
ZIEL = HIER / "fertig"


def main():
    p = HIER / "daten.json"
    if not p.exists():
        sys.exit("Erst kostenlos/daten.example.json nach kostenlos/daten.json kopieren und ausfüllen.")
    d = json.loads(p.read_text(encoding="utf-8"))
    fehlend = [k for k, v in d.items() if isinstance(v, str) and ("..." in v or "DEIN" in v)]
    if fehlend:
        print("⚠ Noch nicht ausgefüllt:", ", ".join(fehlend))

    h = QUELLE.read_text(encoding="utf-8")
    ersetzungen = {
        "https://buy.stripe.com/DEIN-LINK-START": d["stripe_start"],
        "https://buy.stripe.com/DEIN-LINK-WACHSTUM": d["stripe_wachstum"],
        "https://buy.stripe.com/DEIN-LINK-KOMPLETT": d["stripe_komplett"],
        "https://cal.com/DEIN-NAME/15min": d["buchungslink"],
        "hallo@deine-agentur.de": d["email"],
        "DEIN AGENTURNAME": escape(d["agentur_name"]),
    }
    for alt, neu in ersetzungen.items():
        h = h.replace(alt, neu)
    h = re.sub(r"<!--[^>]*?ANPASSEN.*?-->|/\*[^*]*ANPASSEN[^*]*\*/", "", h)  # interne Hinweise entfernen

    ZIEL.mkdir(exist_ok=True)
    (ZIEL / "index.html").write_text(h, encoding="utf-8")

    seite = lambda titel, inhalt: f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{titel} · {escape(d['agentur_name'])}</title>
<style>:root{{--bg:#fbfaf6;--fg:#141414}}@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#f0f0f0}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif;max-width:760px;margin:auto;padding:32px 16px}}a{{color:inherit}}</style>
</head><body><p><a href="index.html">← zurück</a></p>{inhalt}</body></html>"""

    (ZIEL / "impressum.html").write_text(seite("Impressum", f"""<h1>Impressum</h1>
<p>Angaben gemäß § 5 DDG</p>
<p>{escape(d['inhaber'])}<br>{escape(d['agentur_name'])}<br>{escape(d['strasse'])}<br>{escape(d['plz_ort'])}</p>
<p>Telefon: {escape(d['telefon'])}<br>E-Mail: <a href="mailto:{escape(d['email'])}">{escape(d['email'])}</a></p>
{('<p>Umsatzsteuer-ID gemäß § 27a UStG: ' + escape(d['ust_id']) + '</p>') if d.get('ust_id') else '<p>Kleinunternehmer gemäß § 19 UStG.</p>'}
<p>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV: {escape(d['inhaber'])}, Anschrift wie oben.</p>"""), encoding="utf-8")

    ds = HIER / "datenschutz.html"
    if ds.exists():
        (ZIEL / "datenschutz.html").write_text(seite("Datenschutz", ds.read_text(encoding="utf-8")), encoding="utf-8")
    else:
        print("⚠ kostenlos/datenschutz.html fehlt: Text kostenlos erstellen auf https://www.e-recht24.de/muster-datenschutzerklaerung.html\n"
              "  (Häkchen: Netlify-Hosting, Stripe, Cal.com, Tally) und den HTML-Text in kostenlos/datenschutz.html speichern.")
        (ZIEL / "datenschutz.html").write_text(seite("Datenschutz", "<h1>Datenschutzerklärung</h1><p>Wird ergänzt.</p>"), encoding="utf-8")

    print(f"✓ Fertig: {ZIEL}\n→ Diesen Ordner auf https://app.netlify.com/drop ziehen. In 1 Minute online, kostenlos.")


if __name__ == "__main__":
    main()
