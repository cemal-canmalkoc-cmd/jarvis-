"""Ausgaben-Kontrolle: Jarvis gibt ohne dein Okay kein Geld aus.

- Jeder Claude-Aufruf wird mit seinen Kosten mitgezählt (Tokens + Websuchen).
- Automatische Arbeit (Suchrunden, Inserate) läuft nur, wenn du ein Tagesbudget erlaubt hast.
  Standard: 0 $ → Jarvis fragt dich, statt selbst loszulegen.
- Was du ausdrücklich befiehlst (Chat, Siri, Knopf), wird ausgeführt.
"""
from __future__ import annotations

import logging
from datetime import date

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
    """Darf Jarvis von sich aus (ohne Befehl) diesen Betrag ausgeben?"""
    budget = float(config.DAILY_BUDGET_USD or 0)
    return budget > 0 and today_spend() + estimate <= budget


def ask_once(what: str, estimate: float) -> None:
    """Statt selbst Geld auszugeben: einmal pro Tag und Thema nachfragen."""
    from . import messaging
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
