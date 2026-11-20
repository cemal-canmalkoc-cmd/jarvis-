# Google-Maps-Methode: Lokale Betriebe online sichtbar machen

> Ehrlich vorweg: Niemand kann dir 500 €/Tag garantieren. Das hier ist ein echtes
> Dienstleistungsgeschäft. Das Tool automatisiert die Kundensuche – verkaufen und
> liefern musst du selbst. Realistisch: erste Abschlüsse nach 2–4 Wochen.

## Das Geschäftsmodell
1. **Finden:** `leadfinder.py` durchsucht Google Maps (offizielle API) nach Betrieben
   ohne Website, mit wenigen Bewertungen oder schlechter Bewertung.
2. **Ansprechen:** Telefonisch mit dem generierten, personalisierten Leitfaden.
3. **Liefern:** Einfache Website (z. B. WordPress/Framer-Vorlage, 3–5 h Arbeit) +
   Google-Unternehmensprofil optimieren + QR-Bewertungskarten für die Theke.
4. **Wiederkehrend:** 49 €/Monat für Hosting, Pflege, Profil-Updates.

## Rechnung für ~500 €/Tag (≈ 10.000 €/Monat bei 20 Arbeitstagen)
| Quelle | Menge | Umsatz/Monat |
|---|---|---|
| Website-Pakete à 990 € | 8 Abschlüsse | 7.920 € |
| Profil-Pakete à 390 € | 4 Abschlüsse | 1.560 € |
| Monatsabos à 49 € | nach 6 Mon. ~60 Kunden | 2.940 € |

Typische Quote am Telefon: 100 Anrufe → ~15 Gespräche → ~5 Termine → 2 Abschlüsse.
**Also: ca. 50 Anrufe pro Tag.** Am Anfang deutlich weniger Umsatz – die Abos wachsen erst mit der Zeit.

## Einrichtung (einmalig, ~15 Min.)
1. https://console.cloud.google.com → Projekt anlegen → **Places API (New)** aktivieren → API-Key erstellen
   (auf Places API beschränken). Google gewährt monatliches Freikontingent; darüber fallen Kosten an –
   Budget-Alarm setzen!
2. `export GOOGLE_MAPS_API_KEY=dein_key`
3. Testlauf ohne Key: `python leadfinder.py --demo`

## Täglicher Ablauf
```bash
python leadfinder.py --branche "Friseur" --branche "Kosmetikstudio" \
  --stadt "Köln" --stadt "Leverkusen" --min-score 50 --out ergebnisse/$(date +%F)
```
- `leads.csv` in Excel/Google Sheets öffnen → nach Score abtelefonieren, Spalte *Status* pflegen
- `anschreiben.md` = Gesprächsleitfaden pro Betrieb

**Gute Branchen:** Handwerker (Maler, Fliesenleger, Elektriker), Friseure, Kosmetik, Restaurants,
Imbisse, Autowerkstätten, Reinigungsfirmen, Physiotherapie, Fahrschulen.

## Rechtliches (wichtig!)
- **Kalt-E-Mails/Fax/SMS an Firmen ohne Einwilligung sind in DE unzulässig** (§ 7 UWG) → nicht machen.
- Telefonanrufe bei Gewerbetreibenden sind nur bei *mutmaßlicher Einwilligung* erlaubt – konkreten
  Bezug zum Betrieb herstellen (das Skript tut das). Persönlicher Besuch vor Ort ist immer okay
  und hat oft die beste Quote.
- **Niemals Fake-Bewertungen** kaufen oder schreiben – illegal und führt zur Sperrung des Profils.
- Gewerbe anmelden, Kleinunternehmerregelung prüfen, Impressum/Datenschutz bei Kundenseiten.
- Google-Daten gemäß Places-API-Nutzungsbedingungen verwenden (nicht dauerhaft weiterverkaufen).
