"""Das Jarvis-Team: dieselbe KI, aufgeteilt in Abteilungen wie in einer Agentur mit Mitarbeitern.

Jede Abteilung zeigt: was sie macht, was sie heute geschafft hat und – wichtig – woran sie hängt
(z. B. „E-Mail nicht verbunden“). So siehst du auf einen Blick, wo das Geschäft stockt.
"""
from __future__ import annotations

from datetime import date

from . import config, store


def _count(conn, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def status() -> list[dict]:
    from . import ads, budget, inbox, matching
    conn = store.connect()
    today = date.today().isoformat()
    mail_ok = matching.mail_ready() and (store.get_state(conn, "inbox_status") or "").startswith("ok:")
    mail_hint = ("" if mail_ok or config.OUTBOX else
                 "E-Mail nicht verbunden → ⚙️ Outlook „Mit Microsoft anmelden“ oder Gmail mit App-Passwort")
    waiting = _count(conn, "SELECT COUNT(*) FROM outbox WHERE sent IS NULL")
    approved = budget.autonomy_active()
    found = store.potentials_today(conn)
    direct = _count(conn, "SELECT COUNT(*) FROM candidates WHERE found_on=? AND tier!='X' AND phone IS NOT NULL "
                          "AND phone!=''", today)
    firms_today = _count(conn, "SELECT COUNT(*) FROM companies WHERE found_on=?", today)
    firms_all = _count(conn, "SELECT COUNT(*) FROM companies WHERE status NOT IN ('kein_bedarf','nicht_anrufen')")
    firms_mail = _count(conn, "SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email!='' "
                              "AND status NOT IN ('kein_bedarf','nicht_anrufen')")
    apps_today = _count(conn, "SELECT COUNT(*) FROM presentations WHERE substr(sent_on,1,10)=?", today)
    interested = _count(conn, "SELECT COUNT(*) FROM candidates WHERE status='interessiert'")
    in_process = _count(conn, "SELECT COUNT(*) FROM candidates WHERE status IN ('vorgestellt','gespraech')")
    convos_today = _count(conn, "SELECT COUNT(*) FROM convos WHERE substr(updated,1,10)=?", today)
    customers = _count(conn, "SELECT COUNT(*) FROM companies WHERE status IN ('interessiert','kunde')")
    jobs_online = _count(conn, "SELECT COUNT(*) FROM jobs WHERE active=1")
    clicks = sum(int(store.get_state(conn, f"clicks:{today}:{b}") or 0) for b in ("lkw", "pflege", "arzt", "firma"))
    refs = int(store.get_state(conn, f"referrals:{today}") or 0)

    def block(*reasons):
        r = [x for x in reasons if x]
        return {"ok": not r, "problem": " · ".join(r)}

    team = [
        {"emoji": "🔎", "name": "Sara", "rolle": "Sourcing", "aufgabe": "Findet täglich Fahrer, Pflegekräfte und Ärzte im Netz",
         "heute": f"{found} neue Profile · {direct} mit Nummer",
         **block("" if approved else "wartet auf dein „Ja“ für heute")},
        {"emoji": "💬", "name": "Mia", "rolle": "Recruiting", "aufgabe": "Schreibt Bewerber an, beantwortet Fragen, holt Lebensläufe",
         "heute": f"{convos_today} Gespräche · {interested} interessiert",
         **block(mail_hint and "Bewerber-Mails: " + mail_hint)},
        {"emoji": "🤝", "name": "Leon", "rolle": "Vertrieb (Arbeitgeber gewinnen)",
         "aufgabe": "Findet Firmen mit offenen Stellen, schickt passende Profile, verhandelt Vereinbarung",
         "heute": f"{firms_today} neue Firmen · {firms_mail} mit E-Mail · {apps_today} Profile vorbereitet/verschickt · "
                  f"{customers} interessiert" + (f" · 📤 {waiting} Mails warten auf deinen Tipp" if waiting else ""),
         **block(mail_hint, "" if firms_all else "noch keine Firmen gefunden → Jarvis: „Such Speditionen in NRW“")},
        {"emoji": "🗂", "name": "Nora", "rolle": "Disposition", "aufgabe": "Verbindet Firma und Bewerber, Unterlagen, Termine, Nachfassen",
         "heute": f"{in_process} im Prozess (vorgestellt/Gespräch)",
         **block(mail_hint)},
        {"emoji": "📣", "name": "Tim", "rolle": "Marketing", "aufgabe": "Inserate, Stellenbörse, Empfehlungsprogramm",
         "heute": f"{jobs_online} Stellen online · {clicks} Klicks · {refs} Empfehlungen",
         **block("" if ads.facebook_ready() else "Facebook-Seite nicht verbunden (Inserate nur zum Kopieren)")},
        {"emoji": "🧾", "name": "Ben", "rolle": "Backoffice", "aufgabe": "Unterlagen prüfen, Umsatz, Rechnungen (nur mit deiner Freigabe)",
         "heute": f"Umsatz Monat {store.revenue_month(conn)['umsatz']:,.0f} €".replace(",", "."),
         **block()},
    ]
    return team


def summary_text() -> str:
    lines = ["👥 *Dein Jarvis-Team heute*"]
    for m in status():
        lines.append(f"{m['emoji']} {m['name']} ({m['rolle']}): {m['heute']}" + ("" if m["ok"] else f"\n   ⛔ {m['problem']}"))
    return "\n".join(lines)
