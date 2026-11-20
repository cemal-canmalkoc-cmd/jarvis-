#!/usr/bin/env python3
"""Baut die Job-Website automatisch.

1. Holt aktuelle Stellen aus der öffentlichen Jobsuche-API der Bundesagentur für Arbeit
   (Fallback: data/sample_jobs.json, wenn die API nicht erreichbar ist oder --offline gesetzt ist).
2. Erzeugt statische HTML-Seiten (Startseite, Seite pro Stadt, Bewerbung, Arbeitgeber, Schweiz)
   plus sitemap.xml und robots.txt im Ordner _site/.

Keine externen Abhängigkeiten – nur Python-Standardbibliothek.
"""
import html
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
API_KEY = "jobboerse-jobsuche"  # öffentlicher Schlüssel der BA-Jobsuche
BA_DETAIL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"


def slug(text: str) -> str:
    t = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def fetch(was: str, wo: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "was": was, "wo": wo, "umkreis": CFG["umkreis_km"],
        "size": CFG["max_jobs_pro_suche"], "angebotsart": 1, "veroeffentlichtseit": 30,
    })
    req = urllib.request.Request(f"{API}?{params}", headers={"X-API-Key": API_KEY, "User-Agent": "jobsite-builder"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    jobs = []
    for s in data.get("stellenangebote", []):
        ort = s.get("arbeitsort", {}) or {}
        jobs.append({
            "refnr": s.get("refnr", ""),
            "titel": s.get("titel", ""),
            "beruf": s.get("beruf", was),
            "arbeitgeber": s.get("arbeitgeber", ""),
            "ort": ort.get("ort", wo),
            "plz": ort.get("plz", ""),
            "datum": s.get("aktuelleVeroeffentlichungsdatum", ""),
            "stadt": wo,
        })
    return jobs


def load_jobs(offline: bool) -> list[dict]:
    jobs: dict[str, dict] = {}
    fails = 0
    if not offline:
        for wo in CFG["orte"]:
            for was in CFG["suchbegriffe"]:
                if fails >= 3 and not jobs:
                    break  # API offensichtlich nicht erreichbar
                try:
                    for j in fetch(was, wo):
                        if j["refnr"]:
                            jobs.setdefault(j["refnr"], j)
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    print(f"WARN {was}/{wo}: {e}", file=sys.stderr)
    if not jobs:
        print("Keine Live-Daten – nutze data/sample_jobs.json", file=sys.stderr)
        for j in json.loads((ROOT / "data/sample_jobs.json").read_text(encoding="utf-8")):
            j.setdefault("stadt", j["ort"])
            jobs[j["refnr"]] = j
    return sorted(jobs.values(), key=lambda j: j.get("datum", ""), reverse=True)


def page(title: str, desc: str, body: str, depth: int = 0) -> str:
    pre = "../" * depth
    e = html.escape
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="stylesheet" href="{pre}style.css"></head>
<body><header><a class="logo" href="{pre}index.html">{e(CFG['firmenname'])}</a>
<nav><a href="{pre}index.html">Jobs</a><a href="{pre}schweiz.html">Schweiz</a><a href="{pre}arbeitgeber.html">Für Arbeitgeber</a><a class="btn" href="{pre}bewerben.html">Jetzt bewerben</a></nav></header>
<main>{body}</main>
<footer><a href="{pre}impressum.html">Impressum</a> · <a href="{pre}datenschutz.html">Datenschutz</a> ·
Stellendaten: Bundesagentur für Arbeit · Stand {date.today():%d.%m.%Y}</footer>
</body></html>"""


def job_rows(jobs: list[dict], depth: int) -> str:
    pre = "../" * depth
    e = html.escape
    rows = []
    for j in jobs:
        ref = urllib.parse.quote(j["refnr"])
        rows.append(f"""<li class="job"><div><strong>{e(j['titel'])}</strong><br>
<span>{e(j['arbeitgeber'])} · {e(j['plz'])} {e(j['ort'])}</span></div>
<div class="actions"><a href="{BA_DETAIL}{ref}" rel="nofollow noopener" target="_blank">Details</a>
<a class="btn" href="{pre}bewerben.html?ref={ref}&amp;titel={urllib.parse.quote(j['titel'])}">Über uns bewerben</a></div></li>""")
    return "<ul class='jobs'>" + "".join(rows) + "</ul>"


def form(kind: str) -> str:
    action = CFG["formular_endpoint"] or f"mailto:{CFG['kontakt_email']}"
    enctype = "" if CFG["formular_endpoint"] else ' enctype="text/plain"'
    if kind == "kandidat":
        fields = """
<input type="hidden" name="typ" value="Kandidat"><input type="hidden" name="stelle_ref" id="ref">
<label>Stelle<input name="stelle" id="titel" placeholder="optional"></label>
<label>Name*<input name="name" required></label>
<label>E-Mail*<input type="email" name="email" required></label>
<label>Telefon*<input name="telefon" required></label>
<label>Beruf / Qualifikation*<input name="qualifikation" required placeholder="z.B. examinierte Pflegefachkraft"></label>
<label>Berufserfahrung (Jahre)<input type="number" name="erfahrung" min="0"></label>
<label>Wunschort(e)*<input name="wunschort" required placeholder="z.B. Berlin, Zürich"></label>
<label>Verfügbar ab<input type="date" name="verfuegbar"></label>
<label>Gehaltswunsch (brutto/Jahr)<input name="gehalt"></label>
<label>Nachricht<textarea name="nachricht" rows="4"></textarea></label>"""
    else:
        fields = """
<input type="hidden" name="typ" value="Arbeitgeber">
<label>Einrichtung*<input name="einrichtung" required></label>
<label>Ansprechpartner*<input name="name" required></label>
<label>E-Mail*<input type="email" name="email" required></label>
<label>Telefon<input name="telefon"></label>
<label>Gesuchte Positionen*<textarea name="positionen" rows="3" required></textarea></label>"""
    return f"""<form method="post" action="{html.escape(action)}"{enctype} class="form">{fields}
<label class="check"><input type="checkbox" required> Ich willige ein, dass meine Angaben zur Vermittlung gespeichert
und – bei Kandidaten nur nach meiner Zustimmung – an Arbeitgeber weitergegeben werden (<a href="datenschutz.html">Datenschutz</a>).</label>
<button class="btn" type="submit">Absenden</button></form>
<script>const p=new URLSearchParams(location.search);for(const k of["ref","titel"]){{const el=document.getElementById(k);if(el&&p.get(k))el.value=p.get(k);}}</script>"""


def build(offline: bool) -> None:
    jobs = load_jobs(offline)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "stadt").mkdir(parents=True)
    shutil.copy(ROOT / "static/style.css", OUT / "style.css")
    (OUT / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    name = CFG["firmenname"]
    urls = ["index.html", "bewerben.html", "arbeitgeber.html", "schweiz.html"]

    by_city: dict[str, list[dict]] = {}
    for j in jobs:
        by_city.setdefault(j.get("stadt") or j["ort"], []).append(j)

    city_links = "".join(
        f"<a class='chip' href='stadt/{slug(c)}.html'>{html.escape(c)} ({len(v)})</a>"
        for c, v in sorted(by_city.items()))
    hero = f"""<section class="hero"><h1>Pflege- &amp; Medizinjobs – kostenlos vermittelt</h1>
<p>{len(jobs)} aktuelle Stellen. Ein Profil, mehrere Angebote. Für dich 100&nbsp;% kostenlos – die Vermittlungsgebühr zahlt der Arbeitgeber.</p>
<a class="btn big" href="bewerben.html">In 2 Minuten bewerben</a></section>"""
    (OUT / "index.html").write_text(page(
        f"Pflegejobs in Deutschland | {name}", "Aktuelle Jobs für Pflegefachkräfte, Altenpfleger und MFA – kostenlose Vermittlung.",
        hero + f"<h2>Jobs nach Stadt</h2><div class='chips'>{city_links}</div><h2>Neueste Stellen</h2>" + job_rows(jobs[:60], 0)),
        encoding="utf-8")

    for city, cj in by_city.items():
        s = slug(city)
        urls.append(f"stadt/{s}.html")
        (OUT / "stadt" / f"{s}.html").write_text(page(
            f"Pflegejobs {city}: {len(cj)} aktuelle Stellen | {name}",
            f"{len(cj)} Jobs für Pflegekräfte und MFA in {city}. Kostenlos bewerben, wir vermitteln.",
            f"<h1>Pflegejobs in {html.escape(city)}</h1><p>{len(cj)} aktuelle Stellen. "
            f"<a class='btn' href='../bewerben.html'>Profil anlegen – wir melden uns mit passenden Angeboten</a></p>"
            + job_rows(cj, 1), depth=1), encoding="utf-8")

    (OUT / "bewerben.html").write_text(page(
        f"Bewerben | {name}", "Kostenlos bewerben – wir vermitteln dich an Kliniken, Heime und Praxen.",
        "<h1>Kostenlos bewerben</h1><p>Wir melden uns innerhalb von 48&nbsp;Stunden. Dein Profil geht nur mit deiner Zustimmung an Arbeitgeber.</p>"
        + form("kandidat")), encoding="utf-8")

    (OUT / "arbeitgeber.html").write_text(page(
        f"Pflegepersonal finden | {name}", "Geprüfte Pflegefachkräfte – Sie zahlen nur bei erfolgreicher Einstellung.",
        """<h1>Pflegepersonal finden – Zahlung nur bei Erfolg</h1>
<ul class="usp"><li><strong>Keine Vorkosten.</strong> Honorar nur bei Einstellung.</li>
<li><strong>Vorqualifizierte Kandidaten</strong> mit Qualifikation, Verfügbarkeit, Gehaltswunsch.</li>
<li><strong>Faire Konditionen:</strong> Pauschal oder % vom Jahresbrutto, mit Nachbesetzungsgarantie.</li></ul>
<h2>Anfrage stellen</h2>""" + form("arbeitgeber")), encoding="utf-8")

    (OUT / "schweiz.html").write_text(page(
        f"Pflegejobs in der Schweiz | {name}", "Als Pflegefachkraft in die Schweiz – deutlich höhere Gehälter. Kostenlose Beratung.",
        """<h1>Pflege in der Schweiz</h1>
<p>Pflegefachkräfte verdienen in der Schweiz oft deutlich mehr als in Deutschland. Wir beraten dich zu Anerkennung (SRK),
Bewilligung und Wohnen – und bringen dich mit Spitälern und Heimen in Kontakt.</p>
<a class="btn big" href="bewerben.html?titel=Schweiz">Interesse an der Schweiz melden</a>"""), encoding="utf-8")

    for f, t in (("impressum.html", "Impressum"), ("datenschutz.html", "Datenschutzerklärung")):
        src = ROOT / "static" / f
        (OUT / f).write_text(page(t, t, src.read_text(encoding="utf-8")), encoding="utf-8")

    base = CFG["basis_url"].rstrip("/")
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{base}/{u}</loc><lastmod>{date.today()}</lastmod></url>" for u in urls)
        + "</urlset>", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    print(f"OK: {len(jobs)} Jobs, {len(by_city)} Stadtseiten -> {OUT}")


if __name__ == "__main__":
    build(offline="--offline" in sys.argv)
