#!/usr/bin/env python3
"""
Meme-Coin Paper-Trading-Bot (Solana) – NUR SIMULATION, kein echtes Geld.

Strategie (so arbeiten die meisten gaengigen Meme-Coin-Bots im Kern):
  1. Scannen:   neue/trendende Solana-Tokens von DexScreener holen
  2. Filtern:   Scam-Check (RugCheck) + Mindest-Liquiditaet/Volumen/Alter
  3. Einstieg:  Momentum – Kurs steigt kurzfristig, mehr Kaeufe als Verkaeufe
  4. Ausstieg:  Take-Profit, Stop-Loss, Trailing-Stop, maximale Haltedauer
  5. Risiko:    fester Einsatz pro Trade, max. offene Positionen, Tagesverlust-Limit

Es gibt KEINE Gewinngarantie. Teste hier, ob die Strategie ueber Wochen
ueberhaupt profitabel ist, bevor du auch nur an echtes Geld denkst.

Start:
  python3 memebot.py            # live Kursdaten, Spielgeld
  python3 memebot.py --demo     # komplett offline mit zufaelligen Kursen (Logik-Test)
"""

import argparse
import json
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date

try:
    import requests
except ImportError:  # nur fuer --demo nicht noetig
    requests = None

# ----------------------------------------------------------------- Einstellungen
CONFIG = {
    "start_kapital_usd": 1000.0,
    "einsatz_pro_trade_usd": 25.0,     # fester Betrag, nie "alles rein"
    "max_offene_positionen": 5,
    "max_tagesverlust_usd": 100.0,     # danach stoppt der Bot fuer den Tag
    "take_profit_pct": 40.0,           # +40 % -> Gewinn mitnehmen
    "stop_loss_pct": -20.0,            # -20 % -> raus
    "trailing_stop_pct": 15.0,         # faellt 15 % vom Hoch -> raus
    "max_haltedauer_min": 60,
    "gebuehren_slippage_pct": 2.0,     # realistische Kosten pro Kauf UND Verkauf
    # Filter
    "min_liquiditaet_usd": 20_000,
    "min_volumen_1h_usd": 50_000,
    "min_alter_min": 10,               # ganz frische Tokens sind oft Rugs
    "max_alter_std": 24,
    "min_kurs_aenderung_5m_pct": 3.0,  # Momentum
    "min_kauf_verkauf_ratio": 1.3,
    "max_rugcheck_score": 1000,        # niedriger = sicherer
    "scan_intervall_sek": 30,
}

DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/solana/{}"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"
LOGFILE = "trades.jsonl"


# ----------------------------------------------------------------- Datenmodelle
@dataclass
class Position:
    mint: str
    symbol: str
    einstieg: float
    menge: float
    einsatz: float
    zeit: float = field(default_factory=time.time)
    hoch: float = 0.0

    def __post_init__(self):
        self.hoch = self.hoch or self.einstieg


@dataclass
class Konto:
    cash: float
    positionen: dict = field(default_factory=dict)
    tages_pnl: float = 0.0
    tag: date = field(default_factory=date.today)
    trades: int = 0
    gewinner: int = 0


# ----------------------------------------------------------------- Datenquellen
class LiveMarkt:
    def __init__(self):
        if requests is None:
            raise SystemExit("Bitte installieren: pip install requests")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "paper-trading-bot"

    def _get(self, url):
        try:
            r = self.s.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [Netz] {url[:60]}... -> {e}")
            return None

    def kandidaten(self):
        mints = []
        for url in (DEX_BOOSTS, DEX_PROFILES):
            for t in self._get(url) or []:
                if t.get("chainId") == "solana" and t.get("tokenAddress"):
                    mints.append(t["tokenAddress"])
        mints = list(dict.fromkeys(mints))[:30]
        return self.paare(mints)

    def paare(self, mints):
        """Bestes Handelspaar (hoechste Liquiditaet) je Token."""
        out = {}
        if not mints:
            return out
        data = self._get(DEX_TOKENS.format(",".join(mints))) or []
        for p in data:
            mint = p.get("baseToken", {}).get("address")
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if mint and (mint not in out or liq > out[mint]["liq"]):
                tx = (p.get("txns") or {}).get("h1") or {}
                out[mint] = {
                    "mint": mint,
                    "symbol": p.get("baseToken", {}).get("symbol", "?"),
                    "preis": float(p.get("priceUsd") or 0),
                    "liq": liq,
                    "vol_1h": (p.get("volume") or {}).get("h1") or 0,
                    "chg_5m": (p.get("priceChange") or {}).get("m5") or 0,
                    "buys": tx.get("buys", 0),
                    "sells": tx.get("sells", 0),
                    "erstellt_ms": p.get("pairCreatedAt") or 0,
                }
        return out

    def rug_score(self, mint):
        d = self._get(RUGCHECK.format(mint))
        if not d:
            return None, ["RugCheck nicht erreichbar"]
        risiken = [r.get("name", "?") for r in d.get("risks", []) if r.get("level") == "danger"]
        return d.get("score", 99999), risiken


class DemoMarkt:
    """Offline-Simulation: zufaellige Tokens, viele davon Rugs – wie im echten Leben."""

    def __init__(self):
        self.tokens = {}
        self.n = 0

    def _neu(self):
        self.n += 1
        mint = f"DEMO{self.n:04d}"
        self.tokens[mint] = {
            "mint": mint, "symbol": f"MEME{self.n}", "preis": random.uniform(1e-5, 1e-2),
            "liq": random.uniform(5e3, 2e5), "vol_1h": random.uniform(1e4, 5e5),
            "chg_5m": 0.0, "buys": 0, "sells": 0,
            "erstellt_ms": (time.time() - random.uniform(300, 30000)) * 1000,
            "_rug": random.random() < 0.35, "_drift": random.gauss(0, 0.02),
        }

    def kandidaten(self):
        for _ in range(random.randint(0, 3)):
            self._neu()
        for t in self.tokens.values():
            alt = t["preis"]
            if t["_rug"] and random.random() < 0.08:
                t["preis"] *= 0.05          # Rug Pull: -95 %
                t["liq"] *= 0.05
            else:
                t["preis"] *= max(0.01, 1 + t["_drift"] + random.gauss(0, 0.08))
            t["chg_5m"] = (t["preis"] / alt - 1) * 100
            t["buys"] = random.randint(50, 400)
            t["sells"] = random.randint(50, 400)
        return dict(self.tokens)

    def paare(self, mints):
        return {m: self.tokens[m] for m in mints if m in self.tokens}

    def rug_score(self, mint):
        t = self.tokens[mint]
        # Der Checker erkennt nur ~70 % der Rugs – kein Filter ist perfekt
        if t["_rug"] and random.random() < 0.7:
            return 5000, ["Mint Authority aktiv", "Top-10 Holder > 60 %"]
        return random.randint(0, 800), []


# ----------------------------------------------------------------- Bot-Logik
class Bot:
    def __init__(self, markt, cfg):
        self.m = markt
        self.c = cfg
        self.k = Konto(cash=cfg["start_kapital_usd"])
        self.geprueft = {}  # mint -> (ok, grund)

    def log(self, ereignis, **daten):
        daten.update(ereignis=ereignis, zeit=datetime.now().isoformat(timespec="seconds"))
        with open(LOGFILE, "a") as f:
            f.write(json.dumps(daten) + "\n")

    # --- Filter ---------------------------------------------------------
    def filter(self, t):
        c = self.c
        alter_min = (time.time() * 1000 - t["erstellt_ms"]) / 60000 if t["erstellt_ms"] else 0
        if t["preis"] <= 0:
            return False, "kein Preis"
        if t["liq"] < c["min_liquiditaet_usd"]:
            return False, f"Liquiditaet {t['liq']:.0f}$ zu gering"
        if t["vol_1h"] < c["min_volumen_1h_usd"]:
            return False, "Volumen zu gering"
        if not (c["min_alter_min"] <= alter_min <= c["max_alter_std"] * 60):
            return False, f"Alter {alter_min:.0f} min ausserhalb"
        if t["chg_5m"] < c["min_kurs_aenderung_5m_pct"]:
            return False, "kein Momentum"
        if t["buys"] < c["min_kauf_verkauf_ratio"] * max(t["sells"], 1):
            return False, "zu wenig Kaufdruck"
        # Teurer Check zuletzt und gecacht
        if t["mint"] not in self.geprueft:
            score, risiken = self.m.rug_score(t["mint"])
            ok = score is not None and score <= c["max_rugcheck_score"] and not risiken
            self.geprueft[t["mint"]] = (ok, f"RugCheck {score} {risiken}")
        ok, grund = self.geprueft[t["mint"]]
        return (True, "ok") if ok else (False, grund)

    # --- Handel ---------------------------------------------------------
    def kaufen(self, t):
        c = self.c
        einsatz = c["einsatz_pro_trade_usd"]
        if self.k.cash < einsatz:
            return
        eff_preis = t["preis"] * (1 + c["gebuehren_slippage_pct"] / 100)
        pos = Position(t["mint"], t["symbol"], eff_preis, einsatz / eff_preis, einsatz)
        self.k.cash -= einsatz
        self.k.positionen[t["mint"]] = pos
        print(f"  KAUF  {t['symbol']:<10} {einsatz:.2f}$ @ {t['preis']:.8f}")
        self.log("kauf", mint=t["mint"], symbol=t["symbol"], preis=t["preis"], einsatz=einsatz)

    def verkaufen(self, pos, preis, grund):
        eff = preis * (1 - self.c["gebuehren_slippage_pct"] / 100)
        erloes = pos.menge * eff
        pnl = erloes - pos.einsatz
        self.k.cash += erloes
        self.k.tages_pnl += pnl
        self.k.trades += 1
        self.k.gewinner += pnl > 0
        del self.k.positionen[pos.mint]
        print(f"  VERK  {pos.symbol:<10} {grund:<12} PnL {pnl:+.2f}$ ({pnl / pos.einsatz * 100:+.1f} %)")
        self.log("verkauf", mint=pos.mint, symbol=pos.symbol, preis=preis, pnl=round(pnl, 2), grund=grund)

    def positionen_pruefen(self, kurse):
        c = self.c
        for pos in list(self.k.positionen.values()):
            t = kurse.get(pos.mint)
            if not t or t["preis"] <= 0:
                continue
            p = t["preis"]
            pos.hoch = max(pos.hoch, p)
            pct = (p / pos.einstieg - 1) * 100
            vom_hoch = (1 - p / pos.hoch) * 100
            dauer = (time.time() - pos.zeit) / 60
            if pct >= c["take_profit_pct"]:
                self.verkaufen(pos, p, "Take-Profit")
            elif pct <= c["stop_loss_pct"]:
                self.verkaufen(pos, p, "Stop-Loss")
            elif pct > 0 and vom_hoch >= c["trailing_stop_pct"]:
                self.verkaufen(pos, p, "Trailing")
            elif dauer >= c["max_haltedauer_min"]:
                self.verkaufen(pos, p, "Zeitlimit")

    def runde(self):
        if self.k.tag != date.today():
            self.k.tag, self.k.tages_pnl = date.today(), 0.0

        kurse = self.m.kandidaten()
        # Kurse offener Positionen nachladen, falls nicht mehr im Scan
        fehlend = [m for m in self.k.positionen if m not in kurse]
        kurse.update(self.m.paare(fehlend))
        self.positionen_pruefen(kurse)

        if self.k.tages_pnl <= -self.c["max_tagesverlust_usd"]:
            print("  Tagesverlust-Limit erreicht – keine neuen Kaeufe heute.")
            return
        for t in kurse.values():
            if len(self.k.positionen) >= self.c["max_offene_positionen"]:
                break
            if t["mint"] in self.k.positionen:
                continue
            ok, _ = self.filter(t)
            if ok:
                self.kaufen(t)

    def status(self, kurse=None):
        offen = sum(p.menge * p.einstieg for p in self.k.positionen.values())
        gesamt = self.k.cash + offen
        quote = self.k.gewinner / self.k.trades * 100 if self.k.trades else 0
        print(f"[{datetime.now():%H:%M:%S}] Konto ~{gesamt:.2f}$ | Cash {self.k.cash:.2f}$ | "
              f"offen {len(self.k.positionen)} | Trades {self.k.trades} | Trefferquote {quote:.0f} % | "
              f"Heute {self.k.tages_pnl:+.2f}$")


def main():
    ap = argparse.ArgumentParser(description="Meme-Coin Paper-Trading-Bot (Simulation)")
    ap.add_argument("--demo", action="store_true", help="offline mit Zufallskursen")
    ap.add_argument("--runden", type=int, default=0, help="Anzahl Runden (0 = endlos)")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.demo:
        cfg["scan_intervall_sek"] = 0
        cfg["max_haltedauer_min"] = 0.001 * 40  # Demo: Zeitlimit nach ~40 Runden-Sekunden
    bot = Bot(DemoMarkt() if args.demo else LiveMarkt(), cfg)

    print("=== PAPER TRADING – Spielgeld, keine echten Trades ===")
    i = 0
    try:
        while not args.runden or i < args.runden:
            i += 1
            bot.runde()
            if i % 10 == 0 or not args.demo:
                bot.status()
            time.sleep(cfg["scan_intervall_sek"] if not args.demo else 0.05)
    except KeyboardInterrupt:
        pass
    print("\n=== Ergebnis ===")
    bot.status()
    print(f"Alle Trades: {LOGFILE}")


if __name__ == "__main__":
    main()
