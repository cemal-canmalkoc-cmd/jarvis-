"""Ausgaben-Kontrolle: Jarvis gibt ohne dein Okay kein Geld aus.

- Jeder Claude-Aufruf wird mit seinen Kosten mitgezählt (Tokens + Websuchen).
- Automatische Arbeit (Suchrunden, Inserate) läuft nur, wenn du ein Tagesbudget erlaubt hast.
  Standard: 0 $ → Jarvis fragt dich, statt selbst loszulegen.
- Was du ausdrücklich befiehlst (Chat, Siri, Knopf), wird ausgeführt.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import config, store

log = logging.getLogger("jarvis.budget")

# $ pro 1 Mio. Tokens (Eingabe, Ausgabe) – Stand der Preisliste; Websuche 10 $ / 1000 Suchen
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
WEB_SEARCH_USD = 0.01
EST_SEARCH_FOCUS_USD = 0.03   # geschätzte Kosten einer Suche zu einem Fokus
EST_AD_USD = 0.01


def cost_of(model: str, usage) -> float:
    if usage is None:
        return 0.0
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    tokens_in = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    stu = getattr(usage, "server_tool_use", None)
    searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
    return tokens_in / 1e6 * pin + cached / 1e6 * pin * 0.1 + out / 1e6 * pout + searches * WEB_SEARCH_USD


def record(model: str, response) -> float:
    try:
        c = cost_of(model, getattr(response, "usage", None))
        conn = store.connect()
        key = f"spend:{date.today()}"
        store.set_state(conn, key, f"{float(store.get_state(conn, key) or 0) + c:.6f}")
        return c
    except Exception as exc:  # noqa: BLE001 – Zählen darf nie etwas kaputt machen
        log.error("Kosten nicht gezählt: %s", exc)
        return 0.0


def today_spend() -> float:
    return float(store.get_state(store.connect(), f"spend:{date.today()}") or 0)


def auto_allowed(estimate: float) -> bool:
    """Darf Jarvis von sich aus (ohne Befehl) diesen Betrag ausgeben?
    Nur innerhalb des Tagesbudgets UND solange deine 5-Tage-Freigabe läuft."""
    budget = float(config.DAILY_BUDGET_USD or 0)
    reserve = min(float(config.CHAT_MAX_USD or 0), budget)        # für Gespräche freigehalten
    other = today_spend() - chat_spend_today()
    return budget > 0 and other + estimate <= budget - reserve and autonomy_active()


def ask_once(what: str, estimate: float) -> None:
    """Statt selbst Geld auszugeben: einmal pro Tag und Thema nachfragen."""
    from . import messaging
    if config.DAILY_BUDGET_USD and not autonomy_active():
        remind_autonomy()
        return
    conn = store.connect()
    key = f"asked:{date.today()}:{what}"
    if store.get_state(conn, key):
        return
    store.set_state(conn, key, "1")
    hint = ("Automatisches Tagesbudget ist 0 $" if not config.DAILY_BUDGET_USD
            else f"Tagesbudget {config.DAILY_BUDGET_USD:.2f} $ erreicht (heute {today_spend():.2f} $)")
    messaging.notify_owner(
        f"💬 Soll ich {what}? (ca. {estimate:.2f} $)\n{hint} – ich gebe nichts aus, ohne dass du es sagst.\n"
        f"Zum Starten im Jarvis-Chat schreiben: „{'Starte die Web-Suche' if 'such' in what else 'Schreib ein Inserat'}“ "
        f"– oder unter ⚙️ ein Tagesbudget erlauben.")


# --------------------------------------------------------------------------- Gespräche + 5-Tage-Freigabe
def autonomy_until() -> date:
    conn = store.connect()
    v = store.get_state(conn, "auto_until")
    if not v:  # erste Freigabe: ab Installation AUTO_DAYS Tage
        v = (date.today() + timedelta(days=max(1, config.AUTO_DAYS) - 1)).isoformat()
        store.set_state(conn, "auto_until", v)
    return date.fromisoformat(v)


def approved_today() -> bool:
    return store.get_state(store.connect(), f"approved:{date.today()}") == "1"


def autonomy_active() -> bool:
    """Darf Jarvis heute von sich aus Geld ausgeben?
    ASK_DAILY (Standard): nur, wenn du heute in der App „Ja“ getippt hast. Sonst: 5-Tage-Freigabe."""
    if config.ASK_DAILY:
        return approved_today()
    return date.today() <= autonomy_until()


def approve_today() -> str:
    conn = store.connect()
    store.set_state(conn, f"approved:{date.today()}", "1")
    if store.get_state(conn, f"morning_skipped:{date.today()}"):   # Morgensuche jetzt nachholen
        store.set_state(conn, "morning", "")
        store.set_state(conn, f"morning_skipped:{date.today()}", "")
    return (f"✅ Danke! Jarvis arbeitet heute selbstständig – höchstens {config.DAILY_BUDGET_USD:.2f} $. "
            f"Morgen früh fragt er dich wieder.")


def autonomy_continue() -> str:
    if config.ASK_DAILY:
        return approve_today()
    until = date.today() + timedelta(days=max(1, config.AUTO_DAYS) - 1)
    store.set_state(store.connect(), "auto_until", until.isoformat())
    return f"✅ Jarvis arbeitet selbstständig weiter bis {until:%d.%m.%Y} (max. {config.CHAT_MAX_USD:.2f} $ pro Tag für Gespräche)."


def chat_spend_today() -> float:
    return float(store.get_state(store.connect(), f"chat_spend:{date.today()}") or 0)


def add_chat_spend(c: float) -> None:
    conn = store.connect()
    key = f"chat_spend:{date.today()}"
    store.set_state(conn, key, f"{float(store.get_state(conn, key) or 0) + c:.6f}")


def chat_allowed(estimate: float = 0.002) -> bool:
    total = float(config.DAILY_BUDGET_USD or 0)
    return (autonomy_active() and chat_spend_today() + estimate <= float(config.CHAT_MAX_USD or 0)
            and (total <= 0 or today_spend() + estimate <= total))


AUTONOMY_VERSION = "2"


def ensure_defaults() -> None:
    """Einmalig nach dem Update: die vom Inhaber freigegebenen Werte setzen und die 5 Tage neu starten.
    (1 € pro Tag gesamt → 1,00 $ Grenze, bleibt sicher unter 1 €; Gespräche 0,20 $; automatische Bewerbungen an.)"""
    conn = store.connect()
    if store.get_state(conn, "autonomy_version") == AUTONOMY_VERSION:
        return
    for key, val in (("DAILY_BUDGET_USD", "1.0"), ("CHAT_MAX_USD", "0.20"), ("MINIMUM_MAX_USD", "0.30"),
                     ("AUTO_APPLY", "1"), ("AUTO_DAYS", "5"), ("AUTO_INVOICE", "0")):
        store.save_setting(conn, key, val)
    store.set_state(conn, "auto_until", (date.today() + timedelta(days=4)).isoformat())
    store.set_state(conn, "autonomy_version", AUTONOMY_VERSION)


def ensure_defaults_v4() -> None:
    """Einmalig: täglich fragen statt automatisch ausgeben (Wunsch des Inhabers)."""
    conn = store.connect()
    if store.get_state(conn, "defaults_v4"):
        return
    store.save_setting(conn, "ASK_DAILY", "1")
    store.set_state(conn, "defaults_v4", "1")


def ensure_defaults_v3() -> None:
    """Einmalig: Bewerber direkt ins WhatsApp, häufiger suchen (innerhalb 1 $/Tag). Freigabe bleibt wie sie ist."""
    conn = store.connect()
    if store.get_state(conn, "defaults_v3"):
        return
    for key, val in (("CHAT_FIRST", "0"), ("SEARCH_EVERY_HOURS", "2"), ("ADS_PER_DAY", "2")):
        store.save_setting(conn, key, val)
    store.set_state(conn, "defaults_v3", "1")


def remind_autonomy() -> None:
    """Einmal pro Tag melden, wenn die Freigabe abgelaufen oder das Tagesbudget aufgebraucht ist."""
    from . import messaging
    conn = store.connect()
    key = f"auto_reminded:{date.today()}"
    if store.get_state(conn, key):
        return
    store.set_state(conn, key, "1")
    if config.ASK_DAILY and not autonomy_active():
        messaging.notify_owner(f"☀️ Guten Morgen! Darf ich heute nach Leuten suchen und Inserate schreiben – höchstens "
                               f"{config.DAILY_BUDGET_USD:.2f} $? Ohne dein Ja gebe ich nichts aus.\n"
                               f"👉 App öffnen → „✅ Ja, heute arbeiten“ tippen (oder Jarvis „ja“ schreiben).")
    elif not autonomy_active():
        messaging.notify_owner(f"⏸️ Die {config.AUTO_DAYS}-Tage-Freigabe ist abgelaufen. Jarvis gibt kein Geld mehr aus "
                               f"(keine Suche, keine Inserate, Antworten ohne KI) und wartet auf dich: In der App auf "
                               f"„▶️ Weiter ({config.AUTO_DAYS} Tage)“ tippen oder Jarvis „weiter“ sagen.")
    else:
        messaging.notify_owner(f"💬 Gesprächsbudget heute ({config.CHAT_MAX_USD:.2f} $) ist aufgebraucht – "
                               f"weitere Nachrichten beantwortet Jarvis morgen mit KI.")
