#!/usr/bin/env python3
"""
KI-Werbeagentur: produziert die komplette Agentur-Leistung pro Kunde automatisch.

  python agentur.py neu "Firma XY"            -> legt kunden/firma-xy.json (Briefing) an
  python agentur.py produzieren firma-xy      -> Strategie, Google Ads, Meta Ads, 30 Social Posts, Landingpage
  python agentur.py bericht firma-xy zahlen.csv  -> Monatsbericht (HTML) aus Kampagnen-Zahlen
  python agentur.py alle                      -> produziert fuer alle Kunden ohne fertige Lieferung
  python agentur.py rechnung firma-xy         -> Leistungsuebersicht/Rechnungsentwurf (Markdown)

Benoetigt: pip install anthropic  +  ANTHROPIC_API_KEY
"""
import argparse
import csv
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
KUNDEN = BASE / "kunden"
LIEFER = BASE / "lieferungen"
MODEL = "claude-opus-5-5"

PAKETE = {
    "start":    {"preis": 690,  "setup": 490, "posts": 12, "ads": False, "landingpage": False},
    "wachstum": {"preis": 1290, "setup": 490, "posts": 20, "ads": True,  "landingpage": False},
    "komplett": {"preis": 2490, "setup": 990, "posts": 30, "ads": True,  "landingpage": True},
}

BRIEF_VORLAGE = {
    "firma": "", "branche": "", "ort": "", "website": "", "paket": "wachstum",
    "zielgruppe": "", "leistungen": [], "besonderheiten": "", "angebot_aktion": "",
    "ziel": "", "tonalitaet": "freundlich, kompetent", "werbebudget_monat": 300,
    "kontakt_cta": "", "verboten": "",
}

SYSTEM = """Du bist Senior-Performance-Marketer und Texter einer deutschen Werbeagentur für lokale Betriebe.
Du schreibst konkret, lokal und verkaufsstark, ohne leere Floskeln ("Qualität steht bei uns an erster Stelle").
Halte dich an deutsches Werberecht: keine unbelegten Superlative ("der Beste", "Nr. 1"), keine Heilversprechen,
bei Ärzten/Heilberufen das Heilmittelwerbegesetz beachten, keine erfundenen Bewertungen, Zahlen oder Auszeichnungen.
Nutze nur Fakten aus dem Briefing. Fehlt etwas, formuliere neutral statt zu erfinden."""


# ---------------------------------------------------------------- Claude
def client():
    try:
        import anthropic
    except ImportError:
        sys.exit("Bitte zuerst: pip install anthropic   (und ANTHROPIC_API_KEY setzen)")
    return anthropic.Anthropic()


def frage(c, prompt, schema=None, effort="medium"):
    """Ein Claude-Aufruf (gestreamt). Mit schema -> garantiert gueltiges JSON."""
    oc = {"effort": effort}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}
    with c.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        output_config=oc,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Anfrage wurde abgelehnt; Briefing prüfen.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Antwort abgeschnitten (max_tokens).")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(text) if schema else text


def obj(props, req=None):
    return {"type": "object", "properties": props, "required": req or list(props), "additionalProperties": False}


S = {"type": "string"}
LS = {"type": "array", "items": S}

SCHEMA_KAMPAGNE = obj({
    "strategie": obj({
        "positionierung": S, "kernbotschaft": S, "zielgruppen_segmente": LS,
        "kanaele_und_budgetverteilung": S, "kpis": LS, "erste_30_tage": LS}),
    "google_ads": obj({
        "kampagnenname": S, "keywords": LS, "auszuschliessende_keywords": LS,
        "anzeigentitel": LS, "beschreibungen": LS, "sitelinks": LS}),
    "meta_ads": {"type": "array", "items": obj({
        "name": S, "zielgruppe": S, "primaertext": S, "ueberschrift": S, "bildidee": S, "cta": S})},
    "social_posts": {"type": "array", "items": obj({
        "tag": {"type": "integer"}, "kanal": S, "format": S, "thema": S, "text": S, "hashtags": LS, "bildidee": S})},
})


# ---------------------------------------------------------------- Helfer
def slug(s):
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def lade_brief(k):
    p = KUNDEN / f"{k}.json"
    if not p.exists():
        sys.exit(f"{p} fehlt. Vorhandene Kunden: {', '.join(x.stem for x in KUNDEN.glob('*.json'))}")
    b = json.loads(p.read_text(encoding="utf-8"))
    if b.get("paket") not in PAKETE:
        sys.exit(f"paket muss einer von {list(PAKETE)} sein")
    return b


def kuerze(liste, maxlen):
    """Google-Limits erzwingen: Titel 30, Beschreibung 90 Zeichen."""
    return [x.strip() for x in liste if 0 < len(x.strip()) <= maxlen]


# ---------------------------------------------------------------- Kommandos
def cmd_neu(a):
    KUNDEN.mkdir(exist_ok=True)
    p = KUNDEN / f"{slug(a.firma)}.json"
    if p.exists():
        sys.exit(f"{p} existiert schon")
    p.write_text(json.dumps({**BRIEF_VORLAGE, "firma": a.firma}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Briefing angelegt: {p}\nAusfüllen (oder Antworten aus dem Fragebogen einfügen), dann: "
          f"python agentur.py produzieren {p.stem}")


def produzieren(k, c, feedback="", log=print):
    b = lade_brief(k)
    pk = PAKETE[b["paket"]]
    out = LIEFER / k / date.today().strftime("%Y-%m")
    out.mkdir(parents=True, exist_ok=True)
    log(f"→ {b['firma']} (Paket {b['paket']}) …")
    vorher = sorted(p.name for p in (LIEFER / k).glob("*") if p.is_dir() and p != out)

    prompt = f"""Erstelle das komplette Monatspaket für diesen Kunden.

BRIEFING:
{json.dumps(b, ensure_ascii=False, indent=2)}

LIEFERUNG:
- strategie: Positionierung, Kernbotschaft, 2–4 Zielgruppen-Segmente, Kanäle & Verteilung von {b.get('werbebudget_monat', 0)} € Budget/Monat, KPIs, konkrete Schritte erste 30 Tage.
- google_ads: {"lokale Suchkampagne, 15–25 Keywords mit Ortsbezug, 10+ ausschließende Keywords, genau 15 Anzeigentitel (je MAX 30 Zeichen!), genau 4 Beschreibungen (je MAX 90 Zeichen!), 4 Sitelinks (je max 25 Zeichen)." if pk['ads'] else "leere Listen und leerer Name (nicht im Paket)."}
- meta_ads: {"3 Anzeigenvarianten mit unterschiedlichem Winkel (Angebot, Vertrauen/Geschichte, Problem/Lösung)." if pk['ads'] else "leere Liste (nicht im Paket)."}
- social_posts: genau {pk['posts']} Posts, verteilt über 30 Tage (tag 1–30), Mix aus Instagram/Facebook/Google-Unternehmensprofil, Formate Bild/Karussell/Reel. Je Post fertiger Text mit Call-to-Action ({b.get('kontakt_cta', '')}), 3–8 Hashtags inkl. lokaler, konkrete Bildidee, die der Kunde selbst mit dem Handy fotografieren kann.
Tonalität: {b.get('tonalitaet', '')}. Tabu: {b.get('verboten', '') or 'nichts Besonderes'}.
{'Dies ist Monat ' + str(len(vorher) + 1) + ' der Zusammenarbeit: wähle neue Themen und Winkel, wiederhole nicht die Vormonate.' if vorher else ''}
{('ÄNDERUNGSWÜNSCHE DES KUNDEN (unbedingt umsetzen): ' + feedback) if feedback else ''}"""
    d = frage(c, prompt, SCHEMA_KAMPAGNE, effort="high")

    # Strategie
    s = d["strategie"]
    (out / "1_strategie.md").write_text(
        f"# Strategie {b['firma']}, {date.today():%m/%Y}\n\n**Positionierung:** {s['positionierung']}\n\n"
        f"**Kernbotschaft:** {s['kernbotschaft']}\n\n## Zielgruppen\n" + "".join(f"- {x}\n" for x in s["zielgruppen_segmente"]) +
        f"\n## Kanäle & Budget\n{s['kanaele_und_budgetverteilung']}\n\n## KPIs\n" + "".join(f"- {x}\n" for x in s["kpis"]) +
        "\n## Erste 30 Tage\n" + "".join(f"{i}. {x}\n" for i, x in enumerate(s["erste_30_tage"], 1)), encoding="utf-8")

    # Google Ads -> CSV zum Import in Google Ads Editor
    g = d["google_ads"]
    if pk["ads"]:
        titel, besch = kuerze(g["anzeigentitel"], 30), kuerze(g["beschreibungen"], 90)
        with open(out / "2_google_ads.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Campaign", "Ad group", "Keyword", "Match type"])
            for kw in g["keywords"]:
                w.writerow([g["kampagnenname"], "Haupt", kw, "Phrase"])
            for kw in g["auszuschliessende_keywords"]:
                w.writerow([g["kampagnenname"], "", kw, "Negative phrase"])
            w.writerow([])
            w.writerow(["Campaign", "Ad group"] + [f"Headline {i}" for i in range(1, len(titel) + 1)]
                       + [f"Description {i}" for i in range(1, len(besch) + 1)])
            w.writerow([g["kampagnenname"], "Haupt"] + titel + besch)
        log(f"   Google Ads: {len(g['keywords'])} Keywords, {len(titel)} Titel, {len(besch)} Beschreibungen")

        (out / "3_meta_ads.md").write_text(f"# Meta-Anzeigen {b['firma']}\n\n" + "\n".join(
            f"## {m['name']}\n**Zielgruppe:** {m['zielgruppe']}\n\n**Text:**\n{m['primaertext']}\n\n"
            f"**Überschrift:** {m['ueberschrift']}  \n**Button:** {m['cta']}  \n**Bild/Video:** {m['bildidee']}\n"
            for m in d["meta_ads"]), encoding="utf-8")

    # Social-Media-Redaktionsplan
    with open(out / "4_social_redaktionsplan.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Tag", "Kanal", "Format", "Thema", "Text", "Hashtags", "Bildidee"])
        for p in sorted(d["social_posts"], key=lambda x: x["tag"]):
            w.writerow([p["tag"], p["kanal"], p["format"], p["thema"], p["text"], " ".join(p["hashtags"]), p["bildidee"]])
    log(f"   Social: {len(d['social_posts'])} Posts")

    # Landingpage
    if pk["landingpage"]:
        lp = frage(c, f"""Schreibe eine komplette, moderne Landingpage als EINE HTML-Datei (inline CSS, kein JS-Framework,
mobil optimiert, Dark-Mode via prefers-color-scheme, keine externen Bilder: nutze Farbflächen/Platzhalter-Boxen mit Bildbeschreibung).
Ziel: {b.get('ziel', '')}. Hauptaktion: {b.get('kontakt_cta', '')}. Aktion: {b.get('angebot_aktion', '')}.
Abschnitte: Hero mit klarer Aktion, Leistungen, Warum wir (nur Fakten aus dem Briefing), Ablauf/Bestellung, FAQ (4), Kontakt, Footer mit Links "Impressum" und "Datenschutz".
Keine erfundenen Bewertungen, Zahlen oder Siegel.
Briefing: {json.dumps(b, ensure_ascii=False)}
{('Änderungswünsche des Kunden: ' + feedback) if feedback else ''}
Gib NUR den HTML-Code aus, beginnend mit <!doctype html>.""", effort="medium")
        lp = lp[lp.lower().find("<!doctype"):] if "<!doctype" in lp.lower() else lp
        (out / "5_landingpage.html").write_text(lp, encoding="utf-8")
        log("   Landingpage: fertig")

    (out / "LIES_MICH.txt").write_text(
        f"Lieferung {b['firma']}, {date.today():%d.%m.%Y}\n\n"
        "1_strategie.md            → an Kunden schicken / im Kickoff besprechen\n"
        + ("2_google_ads.csv          → Google Ads Editor > Konto > Importieren\n"
           "3_meta_ads.md             → Meta Werbeanzeigenmanager\n" if pk["ads"] else "")
        + "4_social_redaktionsplan   → in Buffer/Later/Meta Business Suite einplanen (CSV-Import)\n"
        + ("5_landingpage.html        → auf Netlify/Vercel hochladen, Impressum ergänzen\n" if pk["landingpage"] else "")
        + "\nVor Veröffentlichung: Fakten, Preise und Öffnungszeiten vom Kunden freigeben lassen.\n", encoding="utf-8")
    log(f"   ✓ {out}")
    return out


def cmd_produzieren(a):
    produzieren(a.kunde, client())


def cmd_alle(a):
    c = client()
    monat = date.today().strftime("%Y-%m")
    for p in sorted(KUNDEN.glob("*.json")):
        if p.stem.startswith("beispiel") and not a.mit_beispiel:
            continue
        if (LIEFER / p.stem / monat / "LIES_MICH.txt").exists():
            print(f"· {p.stem}: diesen Monat schon geliefert")
            continue
        try:
            produzieren(p.stem, c)
        except Exception as e:
            print(f"! {p.stem}: {e}")


def cmd_bericht(a):
    """CSV mit Spalten: kanal;ausgaben;impressionen;klicks;conversions (aus Google/Meta exportiert)."""
    b = lade_brief(a.kunde)
    rows = list(csv.DictReader(open(a.zahlen, encoding="utf-8-sig"), delimiter=";"))
    num = lambda r, k: float(str(r.get(k, 0) or 0).replace(".", "").replace(",", "."))
    sumk = {k: sum(num(r, k) for r in rows) for k in ["ausgaben", "impressionen", "klicks", "conversions"]}
    ctr = sumk["klicks"] / sumk["impressionen"] * 100 if sumk["impressionen"] else 0
    cpa = sumk["ausgaben"] / sumk["conversions"] if sumk["conversions"] else 0
    fazit = frage(client(), f"""Schreibe für den Kunden {b['firma']} ({b['branche']}) eine kurze, ehrliche Monatsauswertung (max. 150 Wörter, Sie-Form,
3 Absätze: Was lief gut, was verbessern wir, nächste Schritte). Ziel des Kunden: {b.get('ziel', '')}.
Zahlen je Kanal: {json.dumps(rows, ensure_ascii=False)}. Summe: {json.dumps(sumk)}; CTR {ctr:.2f} %; Kosten pro Anfrage {cpa:.2f} €.
Beschönige nichts. Nur Text, kein Markdown.""", effort="low")
    zeilen = "".join(f"<tr><td>{html.escape(r.get('kanal', ''))}</td><td>{num(r, 'ausgaben'):.2f} €</td>"
                     f"<td>{num(r, 'impressionen'):.0f}</td><td>{num(r, 'klicks'):.0f}</td><td>{num(r, 'conversions'):.0f}</td></tr>" for r in rows)
    out = LIEFER / a.kunde / date.today().strftime("%Y-%m") / "6_monatsbericht.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monatsbericht {html.escape(b['firma'])}</title><style>
:root{{--bg:#fafaf8;--fg:#191919;--m:#666;--c:#fff;--l:#e5e3de;--a:#1d5fd1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131313;--fg:#eee;--m:#9a9a9a;--c:#1d1d1d;--l:#2e2e2e;--a:#6ea1ff}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif;margin:0;padding:32px 16px}}.w{{max-width:860px;margin:auto}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:20px 0}}
.k div{{background:var(--c);border:1px solid var(--l);border-radius:12px;padding:14px}}.k b{{display:block;font-size:24px;color:var(--a)}}.k span{{color:var(--m)}}
.t{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:8px;border-bottom:1px solid var(--l)}}
p{{white-space:pre-line}}</style></head><body><div class="w"><h1>Monatsbericht {date.today():%m/%Y}</h1><div style="color:var(--m)">{html.escape(b['firma'])}</div>
<div class="k"><div><b>{sumk['ausgaben']:.0f} €</b><span>Werbebudget</span></div><div><b>{sumk['klicks']:.0f}</b><span>Klicks</span></div>
<div><b>{sumk['conversions']:.0f}</b><span>Anfragen</span></div><div><b>{cpa:.2f} €</b><span>pro Anfrage</span></div><div><b>{ctr:.2f} %</b><span>Klickrate</span></div></div>
<h2>Einschätzung</h2><p>{html.escape(fazit.strip())}</p><h2>Je Kanal</h2><div class="t"><table><tr><th>Kanal</th><th>Ausgaben</th><th>Impressionen</th><th>Klicks</th><th>Anfragen</th></tr>{zeilen}</table></div>
</div></body></html>""", encoding="utf-8")
    print(f"Bericht: {out}")


def cmd_rechnung(a):
    b = lade_brief(a.kunde)
    pk = PAKETE[b["paket"]]
    erst = not any((LIEFER / a.kunde).glob("*/LIES_MICH.txt")) or a.erstmonat
    pos = [(f"Agenturleistung Paket „{b['paket'].capitalize()}“, {date.today():%m/%Y}", pk["preis"])]
    if erst:
        pos.insert(0, ("Einrichtung (Konten, Tracking, Strategie)", pk["setup"]))
    netto = sum(p for _, p in pos)
    print(f"# Rechnungsentwurf: {b['firma']}\n")
    for t, p in pos:
        print(f"- {t}: {p:.2f} €")
    print(f"\nNetto: {netto:.2f} €  |  zzgl. 19 % USt.: {netto * .19:.2f} €  |  Brutto: {netto * 1.19:.2f} €")
    print("(Werbebudget zahlt der Kunde direkt an Google/Meta.)")


def main():
    p = argparse.ArgumentParser(description="KI-Werbeagentur")
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("neu"); x.add_argument("firma"); x.set_defaults(f=cmd_neu)
    x = sp.add_parser("produzieren"); x.add_argument("kunde"); x.set_defaults(f=cmd_produzieren)
    x = sp.add_parser("alle"); x.add_argument("--mit-beispiel", action="store_true"); x.set_defaults(f=cmd_alle)
    x = sp.add_parser("bericht"); x.add_argument("kunde"); x.add_argument("zahlen"); x.set_defaults(f=cmd_bericht)
    x = sp.add_parser("rechnung"); x.add_argument("kunde"); x.add_argument("--erstmonat", action="store_true"); x.set_defaults(f=cmd_rechnung)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
