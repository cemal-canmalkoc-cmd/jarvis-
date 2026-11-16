# Jarvis – automatisierte Personalfindung Schweiz (Gesundheitswesen)

Jarvis arbeitet wie ein Recruiter: Er sammelt Kandidatenprofile, prüft sie mit Claude
auf eure Kriterien und legt dir jeden Tag eine **Shortlist** mit **WhatsApp-Buttons** hin.
Ein Klick öffnet WhatsApp mit einer fertigen, persönlichen Nachricht, und du drückst nur noch Senden.

## Was Jarvis sucht (pflegen in `jarvis/config.py`)

**Pflege:** Dipl. Pflegefachpersonen (Akutspital, Psychiatrie, Geriatrie/Langzeitpflege) und FaGe
- Pflicht: Urkunde + Deutsch B2
- Ausländisches Diplom: SRK-Anerkennung nötig
- ⭐ Top: SRK-Anerkennung oder positiver Pre-Check

**Ärzte:** Allg. Innere Medizin, Psychiatrie, Gynäkologie, Radiologie, Anästhesie, Geriatrie, Neurologie, Rehabilitation
- ⭐ Top: MEBEKO-Anerkennung oder positiver Verfahrensstand

## Ablauf

```
Quellen ──► Claude liest Fakten aus ──► Regel-Bewertung ──► Shortlist + WhatsApp-Links
(Ordner, E-Mail, Web)   (Diplom, Deutsch,     (A/B/C/X,         reports/shortlist-DATUM.html
                         SRK/MEBEKO …)         Score 0–100)
```

| Tier | Bedeutung |
|---|---|
| **A** (≥75) | Sofort anschreiben: Kriterien erfüllt, Anerkennung/Pre-Check vorhanden |
| **B** (55–74) | Gut, aber etwas fehlt noch (z.B. SRK-Verfahren läuft) |
| **C** | Später/nachfragen |
| **X** | Pflichtkriterium nicht erfüllt (z.B. Deutsch unter B2, keine Urkunde) |

Die Bewertung steht transparent in `jarvis/scoring.py`. Claude liest nur aus und erfindet nichts.

## Quellen

1. **Ordner `data/inbox/`**: Lebensläufe als PDF, DOCX oder TXT ablegen (Bewerbungen, Exporte aus
   Jobportalen, auf denen ihr Recruiter-Zugang habt, Empfehlungen).
2. **E-Mail-Postfach (IMAP)**: Ungelesene Bewerbungen inklusive Anhänge werden automatisch gelesen.
3. **Web (`--web`)**: Claude sucht öffentliche **Stellengesuche**, also Personen, die selbst
   öffentlich angeben, dass sie eine Stelle suchen, und eine Kontaktmöglichkeit nennen.

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY und deinen Namen eintragen
```

## Benutzung

```bash
python -m jarvis run                 # Ordner + E-Mail verarbeiten, Shortlist erstellen
python -m jarvis run --web           # zusätzlich alle Bereiche im Web suchen
python -m jarvis run --web --focus "Pflegefachfrau Psychiatrie Zürich"
python -m jarvis list                # alle Kandidaten
python -m jarvis status <ID> kontaktiert   # nach dem Anschreiben markieren
```

Danach `reports/shortlist-JJJJ-MM-TT.html` öffnen (auch am Handy), dann auf **WhatsApp öffnen** und Senden.
Bereits markierte Kandidaten erscheinen nicht erneut.

### Täglich automatisch (z.B. 6:30 Uhr)

```cron
30 6 * * * cd /pfad/zu/jarvis- && python -m jarvis run --web >> jarvis.log 2>&1
```

## Wichtig: rechtlich sauber bleiben

- **WhatsApp:** Jarvis verschickt bewusst nicht automatisch. Automatischer Massenversand an
  Personen ohne Einwilligung führt zur Sperre deiner Nummer und kann gegen das UWG verstossen.
  Die Klick-Links sind schnell und sicher.
- **Datenschutz (nDSG/DSGVO):** Nur Daten von Personen verarbeiten, die sich beworben haben oder
  ihre Jobsuche selbst öffentlich gemacht haben. Jede Nachricht enthält eine Opt-out-Möglichkeit.
  Wer „kein Interesse" sagt, markierst du mit `status <ID> kein_interesse`.
- **Kein Scraping** von LinkedIn, XING & Co. (verstösst gegen deren Nutzungsbedingungen).

## Tests

```bash
python -m pytest -q
```
