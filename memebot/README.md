# Meme-Coin Paper-Trading-Bot (Solana)

**Nur Simulation mit Spielgeld.** Es werden keine echten Trades ausgeführt und keine Wallet verbunden.

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

## Wichtig
- Keine Gewinngarantie. Erst über Wochen simulieren und auswerten.
- Gebühren/Slippage (2 % pro Seite) sind eingerechnet, ohne die sieht jede Strategie besser aus.
- Niemals Seed Phrase oder Private Key in Code, Bots oder Websites eingeben.
