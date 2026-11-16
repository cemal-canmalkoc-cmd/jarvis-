#!/usr/bin/env python3
"""
KI-Sprint: Automatische Kundengewinnung fuer ein KI-Automatisierungs-Angebot.

Ablauf (alles per Kommando):
  python sprint.py leads        -> Firmen aus OpenStreetMap holen (Branche x Stadt)
  python sprint.py analyze      -> Websites pruefen: Online-Termine? Chatbot? Stellenanzeigen?
  python sprint.py messages     -> Persoenliche Erstnachricht pro Firma (Claude, sonst Vorlage)
  python sprint.py todo         -> Heutige Aufgaben: wen anrufen / anschreiben / nachfassen
  python sprint.py mark ID STATUS [--notiz "..."]   -> Status setzen
  python sprint.py stats        -> Funnel + Umsatz gegen 10.000-EUR-Ziel
  python sprint.py dashboard    -> dashboard.html erzeugen
  python sprint.py export       -> leads_export.csv (fuer Telefon/LinkedIn)

Status: neu -> kontaktiert -> nachgefasst -> antwort -> termin -> angebot -> gewonnen | verloren
"""
import argparse
import csv
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "pipeline.db"
ZIEL_EUR = 10_000
UA = "Mozilla/5.0 (compatible; KI-Sprint/1.0)"

# OpenStreetMap-Tags pro Branche
BRANCHEN = {
    "zahnarzt": ['nwr["amenity"="dentist"]', 'nwr["healthcare"="dentist"]'],
    "arzt": ['nwr["amenity"="doctors"]'],
    "physio": ['nwr["healthcare"="physiotherapist"]'],
    "handwerk": ['nwr["craft"~"^(electrician|plumber|hvac|roofer|carpenter|painter|tiler)$"]'],
    "makler": ['nwr["office"="estate_agent"]'],
    "steuerberater": ['nwr["office"="tax_advisor"]'],
    "anwalt": ['nwr["office"="lawyer"]'],
    "kosmetik": ['nwr["shop"="beauty"]'],
}

# Was jede Branche typischerweise schmerzt -> Aufhaenger fuer die Nachricht
SCHMERZ = {
    "zahnarzt": "verpasste Anrufe und Terminanfragen ausserhalb der Sprechzeiten",
    "arzt": "ueberlastetes Telefon und Terminvergabe",
    "physio": "Terminvergabe per Telefon und kurzfristige Absagen",
    "handwerk": "Anfragen, die liegen bleiben, weil alle auf der Baustelle sind",
    "makler": "Interessenten-Anfragen, die erst Stunden spaeter beantwortet werden",
    "steuerberater": "wiederkehrende Mandantenfragen und Belegnachforderungen",
    "anwalt": "Erstanfragen und Terminabstimmung",
    "kosmetik": "Terminbuchung per Telefon/WhatsApp und No-Shows",
}

# Angebot ist per config.json ueberschreibbar (z. B. fuer die Werbeagentur, siehe ../agentur/README.md)
ANGEBOT_SATZ = ("Ich richte in 5 Werktagen einen KI-Assistenten ein, der Anfragen rund um die Uhr beantwortet, "
                "Termine direkt einbucht und automatisch nachfasst, zum Festpreis und ohne laufende Agenturkosten.")
ANGEBOT_TELEFON = "Ich baue für {branche}-Betriebe KI-Assistenten, die Anfragen automatisch annehmen und Termine einbuchen."

STATUS = ["neu", "kontaktiert", "nachgefasst", "antwort", "termin", "angebot", "gewonnen", "verloren"]


# ---------------------------------------------------------------- Basis
def cfg():
    p = BASE / "config.json"
    if not p.exists():
        sys.exit("config.json fehlt. Kopiere config.example.json -> config.json und trage deine Daten ein.")
    return json.loads(p.read_text(encoding="utf-8"))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS leads(
      id INTEGER PRIMARY KEY, osm_id TEXT UNIQUE, name TEXT, branche TEXT, stadt TEXT,
      adresse TEXT, telefon TEXT, email TEXT, website TEXT,
      signale TEXT, score INTEGER DEFAULT 0, nachricht TEXT, telefonskript TEXT,
      status TEXT DEFAULT 'neu', umsatz REAL DEFAULT 0, notiz TEXT,
      kontaktiert_am TEXT, naechster_schritt TEXT, erstellt TEXT);
    """)
    return con


def http_get(url, data=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(600_000)
        return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


# ---------------------------------------------------------------- 1. Leads
def overpass_query(stadt, selektoren, limit):
    teile = "".join(f'{s}(area.a);' for s in selektoren)
    return (f'[out:json][timeout:60];area["name"="{stadt}"]["boundary"="administrative"]->.a;'
            f'({teile});out tags center {limit};')


def cmd_leads(a):
    c, con = cfg(), db()
    neu = 0
    for stadt in c["staedte"]:
        for br in c["branchen"]:
            if br not in BRANCHEN:
                print(f"  ! unbekannte Branche '{br}'. Moeglich: {', '.join(BRANCHEN)}")
                continue
            q = overpass_query(stadt, BRANCHEN[br], c.get("max_leads_pro_suche", 150))
            try:
                res = json.loads(http_get("https://overpass-api.de/api/interpreter",
                                          urllib.parse.urlencode({"data": q}).encode(), timeout=90))
            except Exception as e:
                print(f"  ! {stadt}/{br}: {e}")
                continue
            for el in res.get("elements", []):
                t = el.get("tags", {})
                name = t.get("name")
                if not name:
                    continue
                web = t.get("website") or t.get("contact:website") or ""
                tel = t.get("phone") or t.get("contact:phone") or ""
                mail = t.get("email") or t.get("contact:email") or ""
                adr = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", ""),
                                           t.get("addr:postcode", ""), t.get("addr:city", "")] if x)
                try:
                    con.execute("INSERT INTO leads(osm_id,name,branche,stadt,adresse,telefon,email,website,erstellt)"
                                " VALUES(?,?,?,?,?,?,?,?,?)",
                                (f'{el["type"]}/{el["id"]}', name, br, stadt, adr, tel, mail, web,
                                 datetime.now().isoformat(timespec="seconds")))
                    neu += 1
                except sqlite3.IntegrityError:
                    pass
            con.commit()
            print(f"  {stadt} / {br}: {len(res.get('elements', []))} Treffer")
            time.sleep(2)  # Overpass fair nutzen
    print(f"\n{neu} neue Leads gespeichert. Weiter mit: python sprint.py analyze")


# ---------------------------------------------------------------- 2. Analyse
SIGNALE = {
    "online_termin": r"doctolib|jameda|etermin|calendly|cal\.com|terminland|samedi|shore\.com|treatwell|online[- ]?termin|termin online buchen",
    "chatbot": r"tidio|intercom|userlike|crisp\.chat|livechat|chatbot|zendesk|hubspot.*chat|moinai|botpress",
    "kontaktformular": r"<form[^>]*>(?:(?!</form>).){0,4000}(nachricht|message|anfrage)",
    "whatsapp": r"wa\.me/|api\.whatsapp\.com|whatsapp",
    "stellen": r"karriere|stellenangebot|wir suchen|jobs\b|bewerb",
}


def analysiere_html(text):
    low = text.lower()
    s = {k: bool(re.search(p, low, re.S)) for k, p in SIGNALE.items()}
    jahre = [int(j) for j in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})", low)]
    s["copyright_jahr"] = max(jahre) if jahre else None
    mails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    s["email"] = next((m for m in mails if not m.lower().endswith((".png", ".jpg", ".webp"))), "")
    titel = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    s["titel"] = html.unescape(titel.group(1).strip())[:120] if titel else ""
    return s


def score(sig, hat_tel):
    """Je hoeher, desto mehr Automatisierungs-Potenzial = heisser Lead."""
    p = 0
    if not sig.get("online_termin"): p += 3
    if not sig.get("chatbot"): p += 2
    if sig.get("stellen"): p += 3          # suchen Personal -> Entlastung zieht
    if sig.get("copyright_jahr") and sig["copyright_jahr"] < date.today().year - 2: p += 1
    if hat_tel: p += 1
    return p


def cmd_analyze(a):
    con = db()
    rows = con.execute("SELECT * FROM leads WHERE signale IS NULL").fetchall()
    print(f"{len(rows)} Leads zu analysieren ...")
    for i, r in enumerate(rows, 1):
        sig = {"website_erreichbar": False}
        if r["website"]:
            url = r["website"] if r["website"].startswith("http") else "https://" + r["website"]
            try:
                sig.update(analysiere_html(http_get(url, timeout=15)))
                sig["website_erreichbar"] = True
            except Exception as e:
                sig["fehler"] = str(e)[:80]
        sc = score(sig, bool(r["telefon"])) if sig["website_erreichbar"] else (2 if r["telefon"] else 0)
        email = r["email"] or sig.get("email", "")
        con.execute("UPDATE leads SET signale=?, score=?, email=? WHERE id=?",
                    (json.dumps(sig, ensure_ascii=False), sc, email, r["id"]))
        if i % 10 == 0:
            con.commit()
            print(f"  {i}/{len(rows)}")
    con.commit()
    print("Fertig. Weiter mit: python sprint.py messages")


# ---------------------------------------------------------------- 3. Nachrichten
def beobachtung(r, sig):
    if sig.get("stellen"):
        return "dass Sie gerade Personal suchen"
    if sig.get("website_erreichbar") and not sig.get("online_termin"):
        return "dass man bei Ihnen online keinen Termin buchen bzw. keine Anfrage automatisch stellen kann"
    if sig.get("website_erreichbar") and not sig.get("chatbot"):
        return "dass Anfragen auf Ihrer Website nur per Telefon oder Formular reinkommen"
    return "dass Sie vermutlich viele Anfragen telefonisch bekommen"


def vorlage(r, sig, c):
    b = beobachtung(r, sig)
    msg = (f"Guten Tag,\n\nich habe mir {r['name']} angesehen und bemerkt, {b}. "
           f"Viele {r['branche'].capitalize()}-Betriebe verlieren genau dadurch Aufträge und Termine: {SCHMERZ[r['branche']]}.\n\n"
           f"{c.get('angebot_satz', ANGEBOT_SATZ)}\n\n"
           f"Darf ich Ihnen in 15 Minuten zeigen, wie das bei Ihnen aussehen würde? {c['buchungslink']}\n\n"
           f"Viele Grüße\n{c['dein_name']}\n{c['firma']} · {c['telefon']}")
    skript = (f"„Guten Tag, {c['dein_name']} hier. Kurze Frage: Wer kümmert sich bei Ihnen um Terminanfragen? "
              f"... Ich habe gesehen, {b}. {c.get('angebot_telefon', ANGEBOT_TELEFON).format(branche=r['branche'].capitalize())} Hätten Sie diese Woche 15 Minuten, dass ich es Ihnen zeige?“\n"
              f"Einwand 'kein Interesse' -> „Verstehe. Wie viele Anfragen gehen bei Ihnen pro Woche verloren, "
              f"weil keiner ans Telefon kann?“")
    return msg, skript


def claude_nachricht(r, sig, c, client):
    prompt = f"""Schreibe eine kurze B2B-Erstnachricht (LinkedIn oder Kontaktformular, max. 110 Wörter, Sie-Form, Deutsch).

Absender: {c['dein_name']}, {c['firma']}. Angebot: {c.get('angebot_satz', ANGEBOT_SATZ)}
Empfänger: {r['name']} ({r['branche']}, {r['stadt']}). Website-Titel: {sig.get('titel', '')}
Konkrete Beobachtung: {beobachtung(r, sig)}. Typischer Schmerz der Branche: {SCHMERZ[r['branche']]}.
Call-to-Action: 15-Minuten-Gespräch, Link {c['buchungslink']}

Regeln: eine konkrete Beobachtung zuerst, kein Hype, keine Preise, keine Versprechen konkreter Umsatzzahlen, ehrlich und menschlich.
Ende mit Grußformel und Name. Gib nur die Nachricht aus."""
    resp = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=2000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        return None
    txt = "".join(b.text for b in resp.content if b.type == "text").strip()
    return txt or None


def cmd_messages(a):
    c, con = cfg(), db()
    client = None
    if not a.ohne_ki:
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception:
            print("(Kein Claude verfügbar: 'pip install anthropic' + ANTHROPIC_API_KEY. Nutze Vorlagen.)")
    rows = con.execute("SELECT * FROM leads WHERE nachricht IS NULL AND signale IS NOT NULL "
                       "ORDER BY score DESC LIMIT ?", (a.limit,)).fetchall()
    for r in rows:
        sig = json.loads(r["signale"])
        msg, skript = vorlage(r, sig, c)
        if client:
            try:
                msg = claude_nachricht(r, sig, c, client) or msg
            except Exception as e:
                print(f"  ! Claude-Fehler bei {r['name']}: {e} -> Vorlage")
        con.execute("UPDATE leads SET nachricht=?, telefonskript=? WHERE id=?", (msg, skript, r["id"]))
        con.commit()
        print(f"  [{r['score']}] {r['name']}")
    print(f"{len(rows)} Nachrichten erstellt. Weiter mit: python sprint.py todo")


# ---------------------------------------------------------------- 4. Pipeline
FOLLOWUP_TAGE = {"kontaktiert": 3, "nachgefasst": 4}


def nachfass_text(r, c):
    return (f"Guten Tag, kurz nachgehakt zu meiner Nachricht von letzter Woche: Ich hätte diese Woche noch "
            f"2 Plätze frei, um bei {r['name']} einen KI-Assistenten für Anfragen und Termine einzurichten. "
            f"Passt ein kurzer Austausch? {c['buchungslink']}, {c['dein_name']}")


def cmd_todo(a):
    c, con = cfg(), db()
    heute = date.today().isoformat()
    print(f"=== TO-DO {heute} ===\n")
    faellig = con.execute("SELECT * FROM leads WHERE status IN ('kontaktiert','nachgefasst') "
                          "AND naechster_schritt<=? ORDER BY score DESC", (heute,)).fetchall()
    print(f"NACHFASSEN ({len(faellig)}):")
    for r in faellig:
        print(f"  #{r['id']} {r['name']} · {r['telefon'] or r['email'] or r['website']}")
        if a.voll:
            print("    " + nachfass_text(r, c).replace("\n", "\n    "))
    termine = con.execute("SELECT * FROM leads WHERE status IN ('antwort','termin','angebot')").fetchall()
    print(f"\nHEISS, persönlich kümmern ({len(termine)}):")
    for r in termine:
        print(f"  #{r['id']} [{r['status']}] {r['name']} · {r['telefon']} · {r['notiz'] or ''}")
    neu = con.execute("SELECT * FROM leads WHERE status='neu' AND nachricht IS NOT NULL "
                      "ORDER BY score DESC LIMIT ?", (a.anzahl,)).fetchall()
    print(f"\nHEUTE NEU KONTAKTIEREN ({len(neu)}):  danach: python sprint.py mark ID kontaktiert")
    for r in neu:
        kanal = "ANRUFEN " + r["telefon"] if r["telefon"] else ("Formular " + r["website"] if r["website"] else "LinkedIn suchen")
        print(f"\n  #{r['id']} [{r['score']}] {r['name']} ({r['branche']}, {r['stadt']}) · {kanal}")
        if a.voll:
            print("    --- Nachricht ---\n    " + r["nachricht"].replace("\n", "\n    "))
            print("    --- Telefon ---\n    " + r["telefonskript"].replace("\n", "\n    "))


def cmd_mark(a):
    if a.status not in STATUS:
        sys.exit(f"Status muss einer von {STATUS} sein")
    con = db()
    r = con.execute("SELECT * FROM leads WHERE id=?", (a.id,)).fetchone()
    if not r:
        sys.exit("ID nicht gefunden")
    felder = {"status": a.status}
    if a.status in FOLLOWUP_TAGE:
        felder["naechster_schritt"] = (date.today() + timedelta(days=FOLLOWUP_TAGE[a.status])).isoformat()
        if a.status == "kontaktiert":
            felder["kontaktiert_am"] = date.today().isoformat()
    if a.umsatz is not None:
        felder["umsatz"] = a.umsatz
    if a.notiz:
        felder["notiz"] = ((r["notiz"] + " | ") if r["notiz"] else "") + a.notiz
    con.execute(f"UPDATE leads SET {', '.join(k + '=?' for k in felder)} WHERE id=?", (*felder.values(), a.id))
    con.commit()
    print(f"#{a.id} {r['name']} -> {a.status}")


def eur(x):
    return f"{x:,.0f} €".replace(",", ".")


def statistik(con):
    st = {s: 0 for s in STATUS}
    for row in con.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status"):
        st[row["status"]] = row["n"]
    umsatz = con.execute("SELECT COALESCE(SUM(umsatz),0) FROM leads WHERE status='gewonnen'").fetchone()[0]
    return st, umsatz


def cmd_stats(a):
    con = db()
    st, umsatz = statistik(con)
    gesamt = sum(st.values())
    kontaktiert = gesamt - st["neu"]
    print(f"Leads gesamt: {gesamt}   kontaktiert: {kontaktiert}")
    for s in STATUS:
        print(f"  {s:12} {st[s]:5}")
    print(f"\nUMSATZ: {eur(umsatz)} / {eur(ZIEL_EUR)}  ({umsatz / ZIEL_EUR * 100:.0f} %)")
    if kontaktiert:
        print(f"Antwortquote: {(kontaktiert - st['kontaktiert'] - st['nachgefasst']) / kontaktiert * 100:.1f} %")


def cmd_dashboard(a):
    con = db()
    st, umsatz = statistik(con)
    pct = min(100, umsatz / ZIEL_EUR * 100)
    zeilen = "".join(
        f"<tr><td>{r['id']}</td><td>{html.escape(r['name'])}</td><td>{r['branche']}</td><td>{html.escape(r['stadt'])}</td>"
        f"<td>{r['score']}</td><td><span class='s s-{r['status']}'>{r['status']}</span></td>"
        f"<td>{html.escape(r['telefon'] or '')}</td><td>{html.escape(r['notiz'] or '')}</td></tr>"
        for r in con.execute("SELECT * FROM leads WHERE status!='neu' OR score>=6 ORDER BY "
                             "CASE status WHEN 'gewonnen' THEN 0 WHEN 'angebot' THEN 1 WHEN 'termin' THEN 2 "
                             "WHEN 'antwort' THEN 3 ELSE 4 END, score DESC LIMIT 300"))
    funnel = "".join(f"<div class='f'><b>{st[s]}</b><span>{s}</span></div>" for s in STATUS)
    out = f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KI-Sprint Pipeline</title><style>
:root{{--bg:#f7f7f5;--fg:#1b1b1b;--muted:#6b6b6b;--card:#fff;--line:#e4e4e0;--acc:#0b7a5a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--muted:#9a9a9a;--card:#1e1e1e;--line:#2e2e2e;--acc:#3ccf9a}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
.w{{max-width:1100px;margin:auto}}h1{{margin:0 0 4px}}.m{{color:var(--muted)}}
.bar{{background:var(--line);border-radius:8px;height:18px;overflow:hidden;margin:12px 0 24px}}
.bar i{{display:block;height:100%;width:{pct:.1f}%;background:var(--acc)}}
.fs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-bottom:24px}}
.f{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}.f b{{font-size:24px;display:block}}.f span{{color:var(--muted)}}
.t{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
.s{{padding:2px 8px;border-radius:99px;background:var(--line)}}.s-gewonnen{{background:var(--acc);color:#fff}}
</style></head><body><div class="w"><h1>{eur(umsatz)} von {eur(ZIEL_EUR)}</h1>
<div class="m">Stand {datetime.now():%d.%m.%Y %H:%M}</div><div class="bar"><i></i></div>
<div class="fs">{funnel}</div><div class="t"><table><tr><th>#</th><th>Firma</th><th>Branche</th><th>Stadt</th><th>Score</th><th>Status</th><th>Telefon</th><th>Notiz</th></tr>{zeilen}</table></div></div></body></html>"""
    (BASE / "dashboard.html").write_text(out, encoding="utf-8")
    print(f"dashboard.html geschrieben ({BASE / 'dashboard.html'})")


def cmd_export(a):
    con = db()
    rows = con.execute("SELECT id,name,branche,stadt,telefon,email,website,score,status,nachricht "
                       "FROM leads ORDER BY score DESC").fetchall()
    with open(BASE / "leads_export.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(rows[0].keys() if rows else [])
        w.writerows([tuple(r) for r in rows])
    print(f"{len(rows)} Leads -> leads_export.csv")


def main():
    p = argparse.ArgumentParser(description="KI-Sprint: 10.000 € Kundengewinnung")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("leads").set_defaults(f=cmd_leads)
    sp.add_parser("analyze").set_defaults(f=cmd_analyze)
    m = sp.add_parser("messages"); m.add_argument("--limit", type=int, default=100)
    m.add_argument("--ohne-ki", action="store_true"); m.set_defaults(f=cmd_messages)
    t = sp.add_parser("todo"); t.add_argument("--anzahl", type=int, default=40)
    t.add_argument("--voll", action="store_true", help="Nachrichten + Skripte mit ausgeben"); t.set_defaults(f=cmd_todo)
    k = sp.add_parser("mark"); k.add_argument("id", type=int); k.add_argument("status")
    k.add_argument("--umsatz", type=float); k.add_argument("--notiz"); k.set_defaults(f=cmd_mark)
    sp.add_parser("stats").set_defaults(f=cmd_stats)
    sp.add_parser("dashboard").set_defaults(f=cmd_dashboard)
    sp.add_parser("export").set_defaults(f=cmd_export)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
