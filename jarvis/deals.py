"""Vermittlungs-Ablauf von A bis Z – Jarvis treibt jeden Kandidaten Schritt für Schritt zum Abschluss.

  interessiert → Dokumente komplett → Firma mit Interesse (Vereinbarung) → vorgestellt
  → Gespräch → eingestellt (Startdatum) → Rechnung → bezahlt

Was Jarvis allein macht: Dokumente anfordern + erinnern, Unterlagen sammeln, Vereinbarung und Profile an
interessierte Firmen schicken, Gesprächs-/Start-/Rechnungs-Erinnerungen, Umsatz zählen.
Was Cemal-Can macht: Firmen anrufen (Liste + Leitfaden kommen von Jarvis), Ergebnis antippen.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

from . import config, messaging, pricing, store
from .whatsapp import normalize_phone, role_phrase

log = logging.getLogger("jarvis.deals")


# --------------------------------------------------------------------------- Upload-Link für Dokumente
def _secret() -> bytes:
    conn = store.connect()
    s = store.get_state(conn, "doc_secret")
    if not s:
        s = secrets.token_hex(32)
        store.set_state(conn, "doc_secret", s)
    return s.encode()


def doc_token(cand_key: str) -> str:
    return hmac.new(_secret(), cand_key.encode(), hashlib.sha256).hexdigest()[:20]


def check_token(cand_key: str, token: str) -> bool:
    return hmac.compare_digest(doc_token(cand_key), token or "")


def upload_link(cand_key: str) -> str:
    return f"{config.PUBLIC_URL}/dokumente?k={cand_key}&t={doc_token(cand_key)}"


def doc_request_text(row) -> str:
    c = store.load(row)
    a = c.assessment
    first = a.full_name.split()[0] if a.full_name and a.full_name.lower() != "unbekannt" else ""
    st = store.doc_status(store.connect(), row["key"], a.category)
    need = "\n".join(f"• {d}" for d in st["fehlt"]) or "• (alles da – danke!)"
    return (f"Hallo{' ' + first if first else ''}, hier ist {config.RECRUITER_NAME} von {config.AGENCY_NAME}. "
            f"Damit ich Sie sofort passenden Arbeitgebern vorstellen kann, brauche ich noch:\n{need}\n\n"
            f"Einfach hier hochladen (Foto reicht): {upload_link(row['key'])}")


def whatsapp_to_candidate(row, text: str) -> str | None:
    num = normalize_phone(row["phone"])
    return f"https://wa.me/{num}?text={quote(text)}" if num else None


# --------------------------------------------------------------------------- Vereinbarung mit Firmen
def fee_for(row) -> tuple[float, str]:
    a = store.load(row).assessment
    area = pricing.area_for(a.category, a.nursing_field, a.adr)
    p = store.get_prices(store.connect()).get(area)
    if not p or p["modell"] == "prozent_jahreslohn":
        return 0.0, "EUR"
    return float(p["wert"]), ("EUR" if p["modell"] == "pauschal_eur_netto" else "CHF")


def agreement_text(firm) -> str:
    prices = pricing.overview()
    lkw = (firm["branche"] or "") == "lkw" or any(w in f"{firm['needs']} {firm['name']}".lower()
                                                   for w in ("fahrer", "lkw", "spedition", "logistik"))
    areas = ("LKW", "LKW mit ADR") if lkw else ("Pflege", "FaGe", "Arzt")
    lines = [f"- {a}: {prices[a]}" for a in areas if prices.get(a) and prices[a] != "noch nicht festgelegt"]
    return f"""VERMITTLUNGSVEREINBARUNG

zwischen {config.AGENCY_NAME} ({config.RECRUITER_NAME}) – nachfolgend „Vermittler"
und {firm['name']}{', ' + firm['city'] if firm['city'] else ''} – nachfolgend „Auftraggeber"

1. Der Vermittler stellt dem Auftraggeber geeignete Bewerberinnen und Bewerber vor, zunächst anonym.
   Vollständige Unterlagen erhält der Auftraggeber nach Bestätigung dieser Vereinbarung.
2. Honorar (Erfolgshonorar, nur bei Einstellung):
{chr(10).join(lines) or '- gemäss gesondertem Angebot'}
3. Fälligkeit: mit Arbeitsantritt der vermittelten Person, zahlbar innerhalb von 14 Tagen nach Rechnung.
4. Das Honorar fällt an, wenn der Auftraggeber eine vom Vermittler vorgestellte Person innerhalb von
   12 Monaten nach der Vorstellung einstellt – auch bei direkter Kontaktaufnahme.
5. Es wird keine Ersatz- oder Nachbesetzungsgarantie gewährt.
6. Beide Seiten behandeln Bewerberdaten vertraulich und nach DSGVO.

Bestätigung: Eine kurze Antwort „Einverstanden" per E-Mail genügt.

{config.RECRUITER_NAME}, {config.AGENCY_NAME}
(Hinweis: Vorlage – vor dem ersten Einsatz bitte rechtlich prüfen lassen.)"""


def send_agreement_and_profiles(company_id: int) -> str:
    """Firma hat am Telefon Interesse gezeigt → Vereinbarung + anonyme Profile passender Kandidaten senden."""
    from . import matching
    conn = store.connect()
    firm = store.get_company(conn, company_id)
    if not firm:
        return "Firma nicht gefunden."
    if not firm["email"]:
        return f"Für {firm['name']} fehlt die E-Mail-Adresse."
    cands = []
    for r in conn.execute("SELECT * FROM candidates WHERE status IN ('interessiert','vorgestellt') "
                          "ORDER BY score DESC").fetchall():
        if any(m["id"] == company_id for m in matching.matches(conn, r, 5)):
            cands.append(r)
    profiles = "\n\n".join(matching.anonymous_profile(r) for r in cands[:5]) or \
        "(Passende Profile sende ich Ihnen, sobald sie verfügbar sind.)"
    greeting = f"Guten Tag {firm['contact_name']}" if firm["contact_name"] else "Guten Tag"
    body = f"""{greeting}

vielen Dank für das freundliche Gespräch. Wie besprochen erhalten Sie unten die Vermittlungsvereinbarung
und die anonymen Profile passender Bewerberinnen und Bewerber.

{profiles}

Wenn Sie jemanden kennenlernen möchten, antworten Sie einfach mit der Kandidaten-Nr. – ich sende Ihnen dann
die vollständigen Unterlagen und organisiere kurzfristig ein Vorstellungsgespräch.

{agreement_text(firm)}
{chr(10) + 'Tel./WhatsApp: ' + (config.CONTACT_WHATSAPP or config.JARVIS_WHATSAPP_NUMBER) if (config.CONTACT_WHATSAPP or config.JARVIS_WHATSAPP_NUMBER) else ''}"""
    matching.send_email(firm["email"], f"{config.AGENCY_NAME}: Vermittlungsvereinbarung und passende Bewerber",
                        body)
    store.set_company_status(conn, company_id, "interessiert", "Vereinbarung + Profile gesendet")
    with store._lock:
        conn.execute("UPDATE companies SET agreement=? WHERE id=?", (date.today().isoformat(), company_id))
        conn.commit()
    for r in cands[:5]:
        store.record_presentation(conn, r["key"], company_id, "email-vereinbarung")
        if r["status"] == "interessiert":
            store.set_status(conn, r["key"], "vorgestellt", f"anonym vorgestellt bei {firm['name']}")
    return f"✅ Vereinbarung + {len(cands[:5])} Profile an {firm['name']} ({firm['email']}) gesendet."


def send_documents(cand_key: str, company_id: int) -> str:
    """Vollständige Unterlagen an eine Firma senden (nach deren Interesse)."""
    from . import matching
    conn = store.connect()
    row = store.get_candidate(conn, cand_key)
    firm = store.get_company(conn, company_id)
    if not row or not firm or not firm["email"]:
        return "Kandidat, Firma oder E-Mail fehlt."
    files = [d["path"] for d in store.documents(conn, row["key"])]
    cv = store.get_state(conn, f"cv:{row['key']}")
    if cv:
        files.insert(0, cv)
    a = store.load(row).assessment
    body = (f"Guten Tag{' ' + firm['contact_name'] if firm['contact_name'] else ''},\n\nanbei die Unterlagen von "
            f"{a.full_name} ({role_phrase(a)}). Telefon: {a.phone or '-'}.\nGerne vereinbare ich einen "
            f"Vorstellungstermin – nennen Sie mir einfach 2–3 mögliche Zeiten.\n\nFreundliche Grüsse\n"
            f"{config.RECRUITER_NAME}\n{config.AGENCY_NAME}")
    matching.send_email(firm["email"], f"Bewerbung {role_phrase(a)} – {a.full_name}", body, attachments=files)
    store.set_status(conn, row["key"], "vorgestellt", f"Unterlagen an {firm['name']} gesendet")
    return f"✅ Unterlagen von {a.full_name} an {firm['name']} gesendet ({len(files)} Dateien)."


# --------------------------------------------------------------------------- Täglicher Vertriebsplan
def sales_plan(n: int = 8) -> list[dict]:
    """Welche Firmen heute anrufen – mit passendem Kandidaten und Leitfaden."""
    from . import matching
    conn = store.connect()
    interested = conn.execute("SELECT * FROM candidates WHERE status IN ('interessiert','vorgestellt') "
                              "AND tier IN ('A','B','C') ORDER BY score DESC LIMIT 50").fetchall()
    if not interested:  # noch niemand interessiert → mit dem Talentpool (aktiv Jobsuchende) Firmen anrufen
        interested = conn.execute("SELECT * FROM candidates WHERE status IN ('neu','kontaktiert') "
                                  "AND tier IN ('A','B') ORDER BY score DESC LIMIT 50").fetchall()
    tried_today = {r[0] for r in conn.execute("SELECT company_id FROM sales_log WHERE substr(created,1,10)=?",
                                              (date.today().isoformat(),)).fetchall()}
    plan, seen = [], set()
    for cand in interested:
        for m in matching.matches(conn, cand, 5):
            firm = store.get_company(conn, m["id"])
            if (not firm or not firm["phone"] or firm["id"] in seen or firm["id"] in tried_today
                    or firm["status"] in ("kein_bedarf", "nicht_anrufen") or firm["agreement"]):
                continue
            seen.add(firm["id"])
            a = store.load(cand).assessment
            fee, cur = fee_for(cand)
            plan.append({"firma_id": firm["id"], "firma": firm["name"], "ort": firm["city"], "telefon": firm["phone"],
                         "bedarf": firm["needs"], "kandidat": cand["key"][:6].upper(), "kandidat_id": cand["key"],
                         "profil": role_phrase(a), "skript": [
                             f"Guten Tag, {config.RECRUITER_NAME} von {config.AGENCY_NAME}. Sie suchen gerade "
                             f"{firm['needs'] or 'Personal'} – ist das noch aktuell?",
                             f"Ich habe eine/n {role_phrase(a)} aus der Region, sofort erreichbar"
                             + (" – Unterlagen komplett." if store.doc_status(conn, cand["key"], a.category)["komplett"]
                                else "."),
                             f"Kosten nur bei Einstellung: {fee:,.0f} {'€' if cur == 'EUR' else 'CHF'}".replace(",", ".")
                             + " pauschal, keine Vorabkosten.",
                             "Darf ich Ihnen das anonyme Profil und unsere kurze Vereinbarung per E-Mail schicken? "
                             "An welche Adresse?",
                         ]})
            break
        if len(plan) >= n:
            break
    return plan


def record_call(company_id: int, result: str, email: str = "", contact: str = "", note: str = "") -> str:
    conn = store.connect()
    firm = store.get_company(conn, company_id)
    if not firm:
        return "Firma nicht gefunden."
    store.log_sale(conn, company_id, result, note)
    if result == "interesse":
        if email or contact:
            store.set_company_contact(conn, company_id, email or None, contact or None)
        try:
            return send_agreement_and_profiles(company_id)
        except Exception as exc:  # noqa: BLE001
            store.set_company_status(conn, company_id, "interessiert", note)
            return f"Interesse gespeichert, E-Mail nicht gesendet: {exc}"
    if result == "kein_bedarf":
        store.set_company_status(conn, company_id, "kein_bedarf", note)
        return f"{firm['name']}: kein Bedarf – wird nicht mehr vorgeschlagen."
    if result == "nicht_anrufen":
        store.set_company_status(conn, company_id, "nicht_anrufen", note)
        return f"{firm['name']} wird nie wieder angerufen."
    store.set_company_status(conn, company_id, "angerufen", note or result)
    return f"{firm['name']}: {result} – kommt morgen wieder auf die Liste."


# --------------------------------------------------------------------------- Gespräch, Einstellung, Rechnung
def mark_interview(cand_key: str, when: str, company_id: int | None = None) -> str:
    conn = store.connect()
    row = store.get_candidate(conn, cand_key)
    if not row:
        return "Kandidat nicht gefunden."
    firm = store.get_company(conn, company_id) if company_id else None
    store.set_status(conn, row["key"], "gespraech", f"Vorstellungsgespräch {when}" + (f" bei {firm['name']}" if firm else ""))
    store.set_state(conn, f"interview:{row['key']}", when)
    return f"📅 Gespräch am {when} gespeichert – ich erinnere dich und frage danach nach dem Ergebnis."


def mark_hired(cand_key: str, company_id: int | None, start_date: str, fee: float | None = None) -> str:
    conn = store.connect()
    row = store.get_candidate(conn, cand_key)
    if not row:
        return "Kandidat nicht gefunden."
    f, cur = fee_for(row)
    fee = float(fee) if fee else f
    store.add_placement(conn, row["key"], company_id, start_date, fee, cur)
    firm = store.get_company(conn, company_id) if company_id else None
    store.set_status(conn, row["key"], "vermittelt", f"eingestellt ab {start_date}" + (f" bei {firm['name']}" if firm else ""))
    if firm and firm["status"] != "kunde":
        store.set_company_status(conn, firm["id"], "kunde", "erste Vermittlung")
    rev = store.revenue_month(conn, start_date[:7])
    messaging.notify_owner(f"🎉 VERMITTELT: {store.load(row).assessment.full_name}"
                           + (f" → {firm['name']}" if firm else "") + f", Start {start_date}, Honorar "
                           f"{fee:,.0f} {'€' if cur == 'EUR' else 'CHF'}".replace(",", ".")
                           + f"\nUmsatz {rev['monat']}: {rev['umsatz']:,.0f} € / Ziel {config.REVENUE_GOAL:,.0f} €".replace(",", "."))
    return "✅ Als vermittelt gespeichert. Ich erinnere dich am Starttag an die Rechnung."


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def invoice_text(p: dict) -> str:
    conn = store.connect()
    row = store.get_candidate(conn, p["cand_key"])
    firm = store.get_company(conn, p["company_id"]) if p["company_id"] else None
    a = store.load(row).assessment if row else None
    ust = (config.UST_STATUS or "unklar").lower()
    fee = p["fee"] or 0
    if ust.startswith("klein"):
        tax = f"Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.\nGesamt: {eur(fee)}"
    elif ust.startswith("regel"):
        tax = f"zzgl. 19 % USt.: {eur(fee * 0.19)}\nGesamt: {eur(fee * 1.19)}"
    else:
        tax = "(USt.-Status noch klären: Kleinunternehmer § 19 UStG oder zzgl. 19 % USt.)"
    return (f"RECHNUNG – {config.AGENCY_NAME}\n"
            f"An: {firm['name'] if firm else '…'}{', ' + firm['city'] if firm and firm['city'] else ''}\n"
            f"Leistung: Personalvermittlung – {role_phrase(a) if a else ''} {a.full_name if a else ''}, "
            f"Arbeitsantritt {p['start_date']}\nHonorar: {eur(fee)}\n{tax}\nZahlbar innerhalb von 14 Tagen.\n"
            f"(Bitte Rechnungsnummer, deine Adresse, Steuernummer und Bankverbindung ergänzen.)")


# --------------------------------------------------------------------------- Tägliche Antriebsrunde
def daily_drive() -> dict:
    """Einmal täglich: Dokumente anfordern, an Gespräche/Starts/Rechnungen erinnern, Vertriebsliste schicken."""
    from . import matching
    conn = store.connect()
    out = {"dokument_mails": 0, "dokument_whatsapp": [], "erinnerungen": []}
    today = date.today()
    for row in conn.execute("SELECT * FROM candidates WHERE status IN ('interessiert','vorgestellt')").fetchall():
        a = store.load(row).assessment
        st = store.doc_status(conn, row["key"], a.category)
        if st["komplett"]:
            continue
        n = int(store.get_state(conn, f"docreq:{row['key']}") or 0)
        last = store.get_state(conn, f"docreq_at:{row['key']}")
        if n >= 3 or (last and today - date.fromisoformat(last) < timedelta(days=2)):
            continue
        text = doc_request_text(row)
        sent = False
        if a.email and matching.mail_ready():
            try:
                matching.send_email(a.email, "Ihre Unterlagen – nächster Schritt", text)
                out["dokument_mails"] += 1
                sent = True
            except Exception as exc:  # noqa: BLE001
                log.error("Dokument-Mail fehlgeschlagen: %s", exc)
        if not sent and row["consent_whatsapp"]:
            link = whatsapp_to_candidate(row, text)
            if link:
                out["dokument_whatsapp"].append(f"{a.full_name}: {link}")
        store.set_state(conn, f"docreq:{row['key']}", str(n + 1))
        store.set_state(conn, f"docreq_at:{row['key']}", today.isoformat())
    for row in conn.execute("SELECT * FROM candidates WHERE status='gespraech'").fetchall():
        when = store.get_state(conn, f"interview:{row['key']}") or ""
        out["erinnerungen"].append(f"📅 {row['name']}: Gespräch {when} – wie ist es gelaufen? (App → Eingestellt / kein Interesse)")
    from . import invoices
    for p in store.placements(conn, "offen"):
        if p["start_date"] <= today.isoformat():
            if config.AUTO_INVOICE:
                try:
                    res = invoices.send_invoice(p["id"])
                except Exception as exc:  # noqa: BLE001
                    res = f"Rechnung nicht gesendet: {exc}"
                out["erinnerungen"].append(f"🧾 {res}")
            else:
                fehlt = invoices.missing_business_data()
                out["erinnerungen"].append(
                    f"🧾 Rechnung fällig (Start {p['start_date']}): App → Firmen → Vermittlungen → „Rechnung senden“"
                    + (f"\n   Vorher unter ⚙️ eintragen: {', '.join(fehlt)}" if fehlt else ""))
    for p in store.placements(conn, "rechnung"):
        sent = store.get_state(conn, f"invoice_sent:{p['id']}") or p["start_date"]
        if sent <= (today - timedelta(days=14)).isoformat():
            out["erinnerungen"].append(f"💶 Zahlung prüfen: Vermittlung mit Start {p['start_date']} "
                                       f"({p['fee']:,.0f} €) – bezahlt? App → Umsatz".replace(",", "."))
    try:
        from . import convo
        out["erinnerungen"] += [f"📨 {x}" for x in convo.followups()]
    except Exception as exc:  # noqa: BLE001
        log.error("Nachfragen fehlgeschlagen: %s", exc)
    try:
        from . import jobboard
        jb = jobboard.sync()
        if jb["neu"]:
            out["erinnerungen"].append(f"📌 {jb['neu']} neue Stellen in deiner Stellenbörse (aus gefundenen Arbeitgebern)")
    except Exception as exc:  # noqa: BLE001
        log.error("Stellenbörse fehlgeschlagen: %s", exc)
    queue = application_queue(config.AUTO_APPLY_PER_DAY)
    sent_apps = send_applications(queue) if (config.AUTO_APPLY and queue) else []
    plan = sales_plan()
    lines = [f"🚀 Jarvis-Tagesplan {today:%d.%m.}"]
    try:
        from . import team
        lines += [team.summary_text(), ""]
    except Exception as exc:  # noqa: BLE001
        log.error("Team-Status fehlgeschlagen: %s", exc)
    clicks = sum(int(store.get_state(conn, f"clicks:{today - timedelta(days=1)}:{b}") or 0)
                 for b in ("lkw", "pflege", "arzt", "firma"))
    if clicks:
        lines.append(f"💬 Gestern {clicks} Klicks auf deinen WhatsApp-Link")
    if sent_apps:
        lines.append(f"\n📨 {len(sent_apps)} Bewerbungen auf Stellenanzeigen verschickt:")
        lines += sent_apps
    elif queue:
        lines.append(f"\n📨 {len(queue)} Bewerbungen auf Stellenanzeigen bereit – App → Firmen → „Alle senden“")
    rev = store.revenue_month(conn)
    lines.append(f"💶 Umsatz {rev['monat']}: {rev['umsatz']:,.0f} € / Ziel {config.REVENUE_GOAL:,.0f} €".replace(",", "."))
    if plan:
        lines.append(f"\n📞 Optional – nur wenn du Lust hast ({len(plan)} Firmen ohne E-Mail, Leitfaden in der App):")
        lines += [f"• {p['firma']} ({p['ort'] or '?'}) {p['telefon']} – für {p['profil']} #{p['kandidat']}" for p in plan]
    if out["dokument_whatsapp"]:
        lines.append("\n📄 Dokumente per WhatsApp anfordern (antippen, senden):")
        lines += out["dokument_whatsapp"]
    if out["dokument_mails"]:
        lines.append(f"\n📧 {out['dokument_mails']} Dokument-Anfragen per E-Mail verschickt.")
    lines += [""] + out["erinnerungen"] if out["erinnerungen"] else []
    messaging.notify_owner("\n".join(lines))
    out["plan"] = len(plan)
    return out



# --------------------------------------------------------------------------- Bewerbungen auf Stellenanzeigen
def application_queue(limit: int = 10) -> list[dict]:
    """Passende Kandidaten für Firmen mit öffentlicher Bewerbungs-E-Mail (aus einer Stellenanzeige)."""
    from . import matching
    conn = store.connect()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    queue, used_firms = [], set()
    for cand in conn.execute("SELECT * FROM candidates WHERE status IN ('interessiert','vorgestellt') "
                             "AND tier IN ('A','B') ORDER BY score DESC").fetchall():
        for m in matching.matches(conn, cand, 50):
            firm = store.get_company(conn, m["id"])
            if (not firm or not firm["email"] or firm["id"] in used_firms or firm["agreement"]
                    or firm["status"] in ("kein_bedarf", "nicht_anrufen", "kunde")
                    or store.was_presented(conn, cand["key"], firm["id"])):
                continue
            last = store.get_state(conn, f"applied_firm:{firm['id']}")
            if last and last > week_ago:
                continue
            used_firms.add(firm["id"])
            a = store.load(cand).assessment
            queue.append({"kandidat_id": cand["key"], "kandidat": cand["key"][:6].upper(), "profil": role_phrase(a),
                          "firma_id": firm["id"], "firma": firm["name"], "ort": firm["city"], "email": firm["email"],
                          "bedarf": firm["needs"]})
            break
        if len(queue) >= limit:
            break
    return queue


def send_application(cand_key: str, company_id: int) -> str:
    """Anonymes Kandidatenprofil als Antwort auf die Stellenanzeige der Firma senden."""
    from . import matching
    conn = store.connect()
    row = store.get_candidate(conn, cand_key)
    firm = store.get_company(conn, company_id)
    if not row or not firm or not firm["email"]:
        return "Kandidat, Firma oder E-Mail fehlt."
    a = store.load(row).assessment
    price = pricing.for_candidate(a.category, a.nursing_field, a.adr) or "nach Vereinbarung"
    body = f"""Guten Tag,

bezugnehmend auf Ihre Stellenanzeige ({firm['needs'] or 'offene Stelle'}) stelle ich Ihnen eine passende
Fachkraft vor, die sich aktiv bei uns beworben hat und kurzfristig verfügbar ist:

{matching.anonymous_profile(row)}

Wenn Sie die Person kennenlernen möchten, antworten Sie einfach auf diese E-Mail – Sie erhalten dann sofort
die vollständigen Unterlagen und die Kontaktdaten für einen Vorstellungstermin.

Konditionen: {price}. Ohne Einstellung entstehen Ihnen keine Kosten.

Freundliche Grüsse
{config.RECRUITER_NAME}
{config.AGENCY_NAME}

Sie möchten keine weiteren Vorschläge? Eine kurze Antwort „Kein Interesse" genügt."""
    matching.send_email(firm["email"], f"Bewerbung über {config.AGENCY_NAME}: {role_phrase(a)} – kurzfristig verfügbar", body)
    store.record_presentation(conn, row["key"], company_id, "bewerbung-anzeige")
    store.set_state(conn, f"applied_firm:{company_id}", date.today().isoformat())
    if firm["status"] == "neu":
        store.set_company_status(conn, company_id, "angeschrieben", f"Profil {row['key'][:6].upper()} auf Anzeige geschickt")
    if row["status"] == "interessiert":
        store.set_status(conn, row["key"], "vorgestellt", f"auf Anzeige von {firm['name']} vorgestellt")
    return f"✅ {role_phrase(a)} #{row['key'][:6].upper()} an {firm['name']} gesendet."


def send_applications(items: list[dict] | None = None, limit: int = 10) -> list[str]:
    out = []
    for it in (items or application_queue(limit))[:limit]:
        try:
            out.append(send_application(it["kandidat_id"], it["firma_id"]))
        except Exception as exc:  # noqa: BLE001
            out.append(f"⚠️ {it['firma']}: {exc}")
    return out
