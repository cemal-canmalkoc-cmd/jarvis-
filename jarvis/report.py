"""Tägliche Shortlist als HTML (mit WhatsApp-Buttons) und CSV."""
from __future__ import annotations

import csv
import html
from datetime import date
from pathlib import Path

from .config import REPORT_DIR
from .models import ScoredCandidate
from .store import candidate_key

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#5b6470;--line:#e3e6ea;--a:#0f7b3f;--b:#b26a00;--wa:#1fa855}
@media (prefers-color-scheme: dark){:root{--bg:#121417;--card:#1b1e22;--text:#e8eaed;--muted:#9aa3ad;--line:#2b3036;--a:#4fd18b;--b:#f0b04a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif;padding:16px}
main{max-width:900px;margin:auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:12px}
.head{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap}
.name{font-weight:600;font-size:17px}.tier{font-weight:700}.tA{color:var(--a)}.tB{color:var(--b)}
.meta{color:var(--muted);font-size:13px}ul{margin:6px 0;padding-left:18px}.miss{color:var(--b)}
.wa{display:inline-block;background:var(--wa);color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-weight:600;margin-top:6px}
code{font-size:12px;color:var(--muted)}
"""


def write(candidates: list[ScoredCandidate], day: date | None = None) -> tuple[Path, Path]:
    day = day or date.today()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"shortlist-{day.isoformat()}.html"
    csv_path = REPORT_DIR / f"shortlist-{day.isoformat()}.csv"

    cards = []
    for c in candidates:
        a = c.assessment
        role = a.physician_specialty if a.category == "arzt" else a.nursing_field
        e = html.escape
        reasons = "".join(f"<li>{e(r)}</li>" for r in c.reasons)
        missing = "".join(f"<li class='miss'>{e(m)}</li>" for m in c.missing)
        wa = (f"<a class='wa' href='{e(c.whatsapp_link)}' target='_blank'>WhatsApp öffnen</a>"
              if c.whatsapp_link else "")
        cards.append(f"""
<div class="card">
  <div class="head"><span class="name">{e(a.full_name)}</span>
  <span class="tier t{c.tier}">{c.tier} · {c.score}/100</span></div>
  <div class="meta">{e(a.category.upper())} · {e(role or '–')} · Deutsch {e(a.german_level)} ·
  Anerkennung: {e(a.recognition_status)} · {e(a.current_location or 'Ort unbekannt')}</div>
  <p>{e(a.summary)}</p>
  <ul>{reasons}{missing}</ul>
  {wa}
  <div><code>ID {candidate_key(c)} · Quelle: {e(c.source)}</code></div>
</div>""")

    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Jarvis Shortlist</title>
<style>{CSS}</style></head><body><main>
<h1>Jarvis Shortlist – {day.strftime('%d.%m.%Y')}</h1>
<div class="sub">{len(candidates)} Kandidaten zum Anschreiben. Nach dem Kontakt:
<code>python -m jarvis status &lt;ID&gt; kontaktiert</code></div>
{''.join(cards) or '<p>Heute keine neuen passenden Kandidaten.</p>'}
</main></body></html>"""
    html_path.write_text(page, encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Name", "Kategorie", "Bereich", "Tier", "Score", "Deutsch",
                    "Anerkennung", "Ort", "Telefon", "WhatsApp-Link", "Fehlt noch", "Quelle"])
        for c in candidates:
            a = c.assessment
            w.writerow([candidate_key(c), a.full_name, a.category,
                        a.physician_specialty or a.nursing_field, c.tier, c.score, a.german_level,
                        a.recognition_status, a.current_location, a.phone, c.whatsapp_link,
                        " | ".join(c.missing), c.source])
    return html_path, csv_path
