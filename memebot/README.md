# Meme-Coin-Bot (Solana)

## Schnellstart mit echtem Geld (Windows)
1. Python von python.org installieren, dabei **„Add Python to PATH“** anhaken.
2. In Phantom eine **neue Wallet nur für den Bot** anlegen, wenig SOL draufschicken, Private Key exportieren.
3. Doppelklick auf **`START.bat`**, Key einfügen, `JA` eintippen und der Bot handelt.

Mac/Linux: `bash start.sh`. Stoppen: Fenster schließen oder Strg+C.

Standard: **Simulation mit Spielgeld.** Echter Handel nur mit `--live` (siehe unten).
Der Bot scannt alle **3 Sekunden** und kauft/verkauft sofort, wenn alle Regeln erfüllt sind.

## Strategie
1. **Scannen:** neue/trendende Solana-Tokens über die DexScreener-API
2. **Scam-Filter:** RugCheck-Score, Mindest-Liquidität, Volumen, Token-Alter
3. **Einstieg:** Momentum (Kurs +3 % in 5 min, deutlich mehr Käufe als Verkäufe)
4. **Ausstieg:** Take-Profit +40 %, Stop-Loss −20 %, Trailing-Stop 15 %, Zeitlimit
5. **Risiko:** fester Einsatz pro Trade, max. 5 Positionen, Tagesverlust-Limit

Alle Werte stehen oben in `memebot.py` unter `CONFIG`.

## Start
```bash
pip install requests
python3 memebot.py           # echte Kursdaten, Spielgeld
python3 memebot.py --demo    # offline mit Zufallskursen (Logik-Test)
```
Alle Trades werden in `trades.jsonl` protokolliert.

## Profile
| | `vorsichtig` (Standard) | `aggressiv` |
|---|---|---|
| Coins gleichzeitig | max. 5 | **unbegrenzt** |
| Einsatz | fest 25 $ / 0,05 SOL | 5 % vom Guthaben (wächst mit Gewinnen) |
| Gewinnmitnahme | fest bei +40 % | bei 2x die Hälfte verkaufen, Rest läuft mit 25 % Trailing-Stop |
| Stop-Loss | −20 % | −25 % |
| Zeitlimit | 60 min | keins |
| Tagesverlust-Limit | 100 $ | 300 $ (0 = aus) |

```bash
python3 memebot.py --profil aggressiv            # Spielgeld
python3 memebot.py --profil aggressiv --live     # echtes Geld
```

## Echter Handel (`--live`)
1. In Phantom eine **neue, eigene Wallet** nur für den Bot anlegen und wenig SOL draufschicken (z. B. 0,5 SOL).
2. Von **dieser** Wallet den Private Key exportieren (nie die Haupt-Wallet!).
3. Starten:
```bash
pip install requests solders base58
export BOT_PRIVATE_KEY="<Private Key der Bot-Wallet>"
export SOLANA_RPC="https://..."   # optional: schneller eigener RPC (Helius, QuickNode ...)
python3 memebot.py --live
```
Der Bot zeigt Wallet und Guthaben und startet erst, wenn du `JA` eintippst.
Swaps laufen über Jupiter, der Key bleibt lokal. Einstellungen: `live_einsatz_sol` (Standard 0,05 SOL),
harte Obergrenze `live_max_einsatz_sol`, Slippage, Prioritätsgebühr, Tagesverlust-Limit.

## Wichtig
- Keine Gewinngarantie. Erst über Wochen simulieren und auswerten.
- Gebühren/Slippage (2 % pro Seite) sind eingerechnet, ohne die sieht jede Strategie besser aus.
- Niemals Seed Phrase oder Private Key in Code, Bots oder Websites eingeben.
