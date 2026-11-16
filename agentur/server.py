#!/usr/bin/env python3
"""
Automatisierte Agentur: Web-Server, der das Tagesgeschaeft ohne dich abwickelt.

  Kunde kauft (Stripe Payment Link)
    -> Webhook: Kunde anlegen, Fragebogen-Link per Mail
    -> Kunde fuellt Fragebogen aus
    -> Claude produziert die Lieferung (agentur.produzieren)
    -> Mail mit Link zum Kundenportal: ansehen, herunterladen, freigeben oder Aenderung wuenschen
    -> Aenderungswunsch: automatische Ueberarbeitung (max. 2 Runden pro Monat)
    -> Jeden Monat (Stripe invoice.paid): neue Lieferung automatisch + Mail
    -> Kuendigung (subscription.deleted): Produktion stoppt

Start lokal:   python server.py            (http://localhost:8000)
Produktion:    gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 server:app
"""
import json
import secrets
import smtplib
import sqlite3
import threading
import traceback
from datetime import date, datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

from flask import Flask, abort, redirect, request, send_from_directory

import agentur

BASE = Path(__file__).resolve().parent
DB = BASE / "agentur.db"
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8")) if (BASE / "config.json").exists() else {}
MAX_RUNDEN = 2
app = Flask(__name__)
_claude_lock = threading.Lock()


# ---------------------------------------------------------------- DB
def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS kunden(
      id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT, name TEXT, paket TEXT,
      stripe_customer TEXT, stripe_subscription TEXT, slug TEXT,
      status TEXT, runden_monat TEXT, runden INTEGER DEFAULT 0, erstellt TEXT);
    CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, zeit TEXT, kunde_id INTEGER, text TEXT);
    CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY);
    """)
    return con


def log(kid, text):
    with db() as con:
        con.execute("INSERT INTO log(zeit,kunde_id,text) VALUES(?,?,?)", (datetime.now().isoformat(timespec="seconds"), kid, text))
    print(f"[{kid}] {text}")


def kunde(token):
    k = db().execute("SELECT * FROM kunden WHERE token=?", (token,)).fetchone()
    if not k:
        abort(404)
    return k


def setze(kid, **f):
    with db() as con:
        con.execute(f"UPDATE kunden SET {', '.join(x + '=?' for x in f)} WHERE id=?", (*f.values(), kid))


# ---------------------------------------------------------------- Mail
def mail(an, betreff, text):
    s = CFG.get("smtp") or {}
    if not s.get("host"):
        print(f"\n--- MAIL (kein SMTP konfiguriert) an {an}: {betreff}\n{text}\n---")
        return
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = s.get("absender", CFG.get("email")), an, betreff
    m.set_content(text + f"\n\n{CFG.get('agentur_name', '')}\n{CFG.get('email', '')} · {CFG.get('telefon', '')}")
    with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=30) as srv:
        srv.starttls()
        srv.login(s["user"], s["passwort"])
        srv.send_message(m)


def url(pfad):
    return CFG.get("basis_url", "http://localhost:8000").rstrip("/") + pfad


# ---------------------------------------------------------------- Ablauf
def neuer_kunde(email, name, paket, customer="", subscription=""):
    token = secrets.token_urlsafe(18)
    with db() as con:
        cur = con.execute("INSERT INTO kunden(token,email,name,paket,stripe_customer,stripe_subscription,status,erstellt)"
                          " VALUES(?,?,?,?,?,?,?,?)", (token, email, name, paket, customer, subscription,
                                                      "warte_fragebogen", datetime.now().isoformat(timespec="seconds")))
        kid = cur.lastrowid
    log(kid, f"Neuer Kunde {email}, Paket {paket}")
    mail(email, "Willkommen! Ihr nächster Schritt (10 Minuten)",
         f"Guten Tag{(' ' + name) if name else ''},\n\nvielen Dank für Ihre Buchung des Pakets „{paket.capitalize()}“.\n\n"
         f"Bitte füllen Sie jetzt den kurzen Fragebogen aus. Danach erstellen wir Ihre Strategie, Anzeigen und Inhalte, "
         f"und Sie erhalten alles zur Freigabe:\n\n{url('/start/' + token)}\n\nViele Grüße")
    return token


def produktion_starten(kid, feedback=""):
    def job():
        k = db().execute("SELECT * FROM kunden WHERE id=?", (kid,)).fetchone()
        setze(kid, status="in_produktion")
        try:
            with _claude_lock:  # Produktionen nacheinander, schont Rate-Limits
                agentur.produzieren(k["slug"], agentur.client(), feedback=feedback, log=lambda t: log(kid, t))
            setze(kid, status="zur_freigabe")
            mail(k["email"], "Ihre Inhalte sind fertig, bitte kurz prüfen",
                 f"Guten Tag,\n\nIhre Inhalte für diesen Monat sind fertig. Bitte sehen Sie sich alles an und geben Sie es frei "
                 f"oder schreiben Sie uns Ihre Änderungswünsche:\n\n{url('/portal/' + k['token'])}\n\nViele Grüße")
        except Exception as e:
            setze(kid, status="fehler")
            log(kid, "FEHLER: " + "".join(traceback.format_exception_only(e)).strip())
            if CFG.get("email"):
                mail(CFG["email"], f"Produktionsfehler Kunde {kid}", traceback.format_exc())
    threading.Thread(target=job, daemon=True).start()


# ---------------------------------------------------------------- Stripe
@app.post("/webhook/stripe")
def stripe_webhook():
    import stripe
    payload = request.get_data()
    try:
        stripe.Webhook.construct_event(payload, request.headers.get("Stripe-Signature"), CFG["stripe_webhook_secret"])
    except Exception:
        abort(400)
    ev = json.loads(payload)
    with db() as con:
        if con.execute("SELECT 1 FROM events WHERE id=?", (ev["id"],)).fetchone():
            return "doppelt", 200
        con.execute("INSERT INTO events(id) VALUES(?)", (ev["id"],))
    o = ev["data"]["object"]
    typ = ev["type"]

    if typ == "checkout.session.completed":
        paket = CFG.get("payment_links", {}).get(o.get("payment_link") or "", "wachstum")
        cd = o.get("customer_details") or {}
        neuer_kunde(cd.get("email", ""), cd.get("name", ""), paket, o.get("customer") or "", o.get("subscription") or "")

    elif typ == "invoice.paid" and o.get("billing_reason") == "subscription_cycle":
        k = db().execute("SELECT * FROM kunden WHERE stripe_customer=? AND status!='gekuendigt'", (o.get("customer"),)).fetchone()
        if k and k["slug"]:
            log(k["id"], "Monatszahlung erhalten → neue Monatsproduktion")
            setze(k["id"], runden=0, runden_monat=date.today().strftime("%Y-%m"))
            produktion_starten(k["id"])

    elif typ == "customer.subscription.deleted":
        k = db().execute("SELECT * FROM kunden WHERE stripe_subscription=? OR stripe_customer=?",
                         (o.get("id"), o.get("customer"))).fetchone()
        if k:
            setze(k["id"], status="gekuendigt")
            log(k["id"], "Abo gekündigt")
    return "ok", 200


# ---------------------------------------------------------------- Seiten
CSS = """<style>:root{--bg:#fbfaf6;--fg:#141414;--m:#5f5f5f;--c:#fff;--l:#e7e3da;--a:#d9480f;--af:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#f0f0f0;--m:#a3a3a3;--c:#1b1b1b;--l:#2d2d2d;--a:#ff8a4c;--af:#1a0b03}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif;padding:32px 16px}
.w{max-width:900px;margin:auto}.c{background:var(--c);border:1px solid var(--l);border-radius:14px;padding:22px;margin:16px 0}
label{display:block;font-weight:600;margin:16px 0 4px}small{color:var(--m);font-weight:400}
input,textarea,select{width:100%;padding:10px;border:1px solid var(--l);border-radius:8px;background:var(--bg);color:var(--fg);font:inherit}
textarea{min-height:80px}.btn{display:inline-block;background:var(--a);color:var(--af);border:0;padding:12px 20px;border-radius:10px;font:inherit;font-weight:650;cursor:pointer;text-decoration:none}
.btn.alt{background:transparent;color:var(--fg);border:1px solid var(--l)}.m{color:var(--m)}pre{white-space:pre-wrap;font:inherit}
.t{overflow-x:auto}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--l);padding:8px;text-align:left;vertical-align:top}
.s{display:inline-block;padding:2px 10px;border-radius:99px;background:var(--l)}</style>"""


def seite(titel, inhalt):
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(titel)}</title>{CSS}</head><body><div class="w">{inhalt}</div></body></html>')


@app.get("/")
def startseite():
    return send_from_directory(BASE / "website", "index.html")


FRAGEN = [
    ("firma", "Name Ihres Betriebs", "input", ""),
    ("branche", "Branche", "input", "z. B. Elektriker, Zahnarztpraxis, Café"),
    ("ort", "Ort / Einzugsgebiet", "input", "z. B. München und 20 km Umkreis"),
    ("website", "Ihre Website (falls vorhanden)", "input", ""),
    ("leistungen", "Ihre wichtigsten Leistungen/Produkte", "textarea", "eine pro Zeile"),
    ("zielgruppe", "Wer sind Ihre idealen Kunden?", "textarea", ""),
    ("besonderheiten", "Was unterscheidet Sie von der Konkurrenz?", "textarea", "nur echte Fakten, z. B. Familienbetrieb seit 1990, 24h-Notdienst"),
    ("ziel", "Was soll die Werbung vor allem bringen?", "textarea", "z. B. mehr Anfragen für Badsanierungen"),
    ("angebot_aktion", "Aktuelles Angebot / Aktion (optional)", "input", ""),
    ("kontakt_cta", "Wie sollen Kunden Sie kontaktieren?", "input", "z. B. Anruf unter 089 123456 oder Formular auf der Website"),
    ("tonalitaet", "Wie sollen wir klingen?", "input", "z. B. locker und humorvoll / seriös und sachlich"),
    ("werbebudget_monat", "Monatliches Werbebudget für Google/Meta in €", "input", "Zahlen Sie direkt an Google/Meta; 0 wenn nur Social Media"),
    ("verboten", "Was dürfen wir auf keinen Fall sagen?", "textarea", "optional"),
]


@app.route("/start/<token>", methods=["GET", "POST"])
def fragebogen(token):
    k = kunde(token)
    if request.method == "POST":
        f = request.form
        brief = {key: f.get(key, "").strip() for key, *_ in FRAGEN}
        brief["leistungen"] = [x.strip() for x in brief["leistungen"].splitlines() if x.strip()]
        try:
            brief["werbebudget_monat"] = int(float(brief["werbebudget_monat"].replace(",", ".") or 0))
        except ValueError:
            brief["werbebudget_monat"] = 0
        brief["paket"] = k["paket"]
        if not brief["firma"] or not brief["branche"]:
            return redirect(request.url)
        slug = k["slug"] or f"{agentur.slug(brief['firma'])}-{k['id']}"
        agentur.KUNDEN.mkdir(exist_ok=True)
        (agentur.KUNDEN / f"{slug}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        setze(k["id"], slug=slug, name=brief["firma"], runden=0, runden_monat=date.today().strftime("%Y-%m"))
        log(k["id"], "Fragebogen ausgefüllt")
        produktion_starten(k["id"])
        return redirect(f"/portal/{token}")
    felder = "".join(
        f'<label>{escape(t)} <small>{escape(h)}</small></label>'
        + (f'<textarea name="{n}"></textarea>' if typ == "textarea" else f'<input name="{n}">')
        for n, t, typ, h in FRAGEN)
    return seite("Fragebogen", f'<h1>Willkommen!</h1><p class="m">10 Minuten, dann legen wir los. '
                 f'Paket: <b>{escape(k["paket"].capitalize())}</b></p><form method="post" class="c">{felder}'
                 f'<p style="margin-top:24px"><button class="btn">Absenden &amp; Produktion starten</button></p></form>')


def letzte_lieferung(slug):
    d = agentur.LIEFER / slug
    monate = sorted([p for p in d.glob("*") if p.is_dir()], reverse=True) if d.exists() else []
    return monate[0] if monate else None


@app.get("/portal/<token>")
def portal(token):
    k = kunde(token)
    st = k["status"]
    kopf = f'<h1>{escape(k["name"] or "Ihr Kundenportal")}</h1><p class="m">Paket {escape(k["paket"].capitalize())} · Status: <span class="s">{escape(st.replace("_", " "))}</span></p>'
    if st == "warte_fragebogen":
        return seite("Portal", kopf + f'<a class="btn" href="/start/{token}">Fragebogen ausfüllen</a>')
    if st == "in_produktion":
        return seite("Portal", kopf + '<div class="c">Ihre Inhalte werden gerade erstellt. Das dauert einige Minuten. '
                     'Sie bekommen eine E-Mail, sobald alles fertig ist.</div><script>setTimeout(()=>location.reload(),30000)</script>')
    if st == "fehler":
        return seite("Portal", kopf + '<div class="c">Bei der Erstellung gab es ein technisches Problem. Wir sind informiert und melden uns.</div>')
    out = letzte_lieferung(k["slug"])
    if not out:
        return seite("Portal", kopf)
    teile = []
    if (out / "1_strategie.md").exists():
        teile.append(f'<div class="c"><h2>Strategie</h2><pre>{escape((out / "1_strategie.md").read_text(encoding="utf-8"))}</pre></div>')
    if (out / "3_meta_ads.md").exists():
        teile.append(f'<div class="c"><h2>Anzeigen</h2><pre>{escape((out / "3_meta_ads.md").read_text(encoding="utf-8"))}</pre></div>')
    sp = out / "4_social_redaktionsplan.csv"
    if sp.exists():
        import csv
        rows = list(csv.reader(sp.open(encoding="utf-8-sig"), delimiter=";"))
        teile.append('<div class="c"><h2>Social-Media-Plan</h2><div class="t"><table>' + "".join(
            "<tr>" + "".join(f"<td>{escape(x)}</td>" for x in (r[0], r[1], r[4], r[6])) + "</tr>" for r in rows) + "</table></div></div>")
    dateien = " ".join(f'<a class="btn alt" href="/portal/{token}/datei/{out.name}/{p.name}">{escape(p.name)}</a>'
                       for p in sorted(out.iterdir()) if p.name != "LIES_MICH.txt")
    teile.append(f'<div class="c"><h2>Downloads</h2><p style="display:flex;gap:8px;flex-wrap:wrap">{dateien}</p></div>')
    if st == "zur_freigabe":
        rest = MAX_RUNDEN - (k["runden"] or 0)
        teile.append(f'<div class="c"><h2>Freigabe</h2><form method="post" action="/portal/{token}/freigabe">'
                     f'<button class="btn">Alles freigeben</button></form>'
                     + (f'<form method="post" action="/portal/{token}/aenderung"><label>Änderungswünsche <small>noch {rest} Überarbeitung(en) diesen Monat</small></label>'
                        f'<textarea name="feedback" required></textarea><p><button class="btn alt">Überarbeiten lassen</button></p></form>' if rest > 0 else
                        '<p class="m">Die Überarbeitungen für diesen Monat sind aufgebraucht. Für Wünsche antworten Sie einfach auf unsere E-Mail.</p>')
                     + "</div>")
    elif st == "aktiv":
        teile.append('<div class="c">✓ Freigegeben. Neue Inhalte erhalten Sie automatisch zum nächsten Abrechnungsmonat.</div>')
    return seite("Portal", kopf + "".join(teile))


@app.get("/portal/<token>/datei/<monat>/<name>")
def datei(token, monat, name):
    k = kunde(token)
    return send_from_directory(agentur.LIEFER / k["slug"] / monat, name, as_attachment=not name.endswith(".html"))


@app.post("/portal/<token>/freigabe")
def freigabe(token):
    k = kunde(token)
    setze(k["id"], status="aktiv")
    log(k["id"], "Vom Kunden freigegeben")
    if CFG.get("email"):
        mail(CFG["email"], f"Freigabe: {k['name']}", f"{k['name']} hat freigegeben. Lieferung: {letzte_lieferung(k['slug'])}")
    return redirect(f"/portal/{token}")


@app.post("/portal/<token>/aenderung")
def aenderung(token):
    k = kunde(token)
    fb = request.form.get("feedback", "").strip()[:3000]
    if k["status"] != "zur_freigabe" or (k["runden"] or 0) >= MAX_RUNDEN or not fb:
        return redirect(f"/portal/{token}")
    setze(k["id"], runden=(k["runden"] or 0) + 1)
    log(k["id"], f"Änderungswunsch: {fb[:200]}")
    produktion_starten(k["id"], feedback=fb)
    return redirect(f"/portal/{token}")


@app.get("/admin")
def admin():
    if not CFG.get("admin_passwort") or request.args.get("pw") != CFG["admin_passwort"]:
        abort(403)
    con = db()
    ks = con.execute("SELECT * FROM kunden ORDER BY id DESC").fetchall()
    preise = {p: v["preis"] for p, v in agentur.PAKETE.items()}
    mrr = sum(preise.get(k["paket"], 0) for k in ks if k["status"] not in ("gekuendigt", "warte_fragebogen"))
    zeilen = "".join(f'<tr><td>{k["id"]}</td><td>{escape(k["name"] or "")}</td><td>{escape(k["email"] or "")}</td><td>{k["paket"]}</td>'
                     f'<td><span class="s">{k["status"]}</span></td><td><a href="/portal/{k["token"]}">Portal</a></td></tr>' for k in ks)
    logs = "".join(f'<tr><td>{l["zeit"]}</td><td>{l["kunde_id"]}</td><td>{escape(l["text"])}</td></tr>'
                   for l in con.execute("SELECT * FROM log ORDER BY id DESC LIMIT 50"))
    return seite("Admin", f'<h1>{len(ks)} Kunden · {mrr:,} € MRR</h1>'.replace(",", ".")
                 + f'<div class="c t"><table><tr><th>#</th><th>Firma</th><th>E-Mail</th><th>Paket</th><th>Status</th><th></th></tr>{zeilen}</table></div>'
                 + f'<h2>Protokoll</h2><div class="c t"><table>{logs}</table></div>')


@app.post("/test/kauf")
def testkauf():
    """Nur im Testmodus: simuliert einen Stripe-Kauf."""
    if not CFG.get("testmodus"):
        abort(404)
    token = neuer_kunde(request.form.get("email", "test@example.com"), "Test", request.form.get("paket", "wachstum"))
    return redirect(f"/start/{token}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
