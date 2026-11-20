# Der digitale Mitarbeiter

Läuft **jede Stunde automatisch** (GitHub Actions) und erledigt die Vermittlungsarbeit per E-Mail.

## Was er selbstständig macht
| Situation | Was der Mitarbeiter tut |
|---|---|
| Neue Bewerbung (Formular oder E-Mail) | Legt Kandidat an, antwortet sofort, holt die **Zustimmung zur Weitergabe** ein (Antwort „JA“) |
| Kandidat antwortet „JA“ | Schaltet ihn aktiv und bestätigt |
| Keine Antwort nach 3 Tagen | Einmalige Erinnerung |
| Einrichtung fragt nach Personal | Schickt die **Honorar-Konditionen** und bittet um „EINVERSTANDEN“ |
| Einrichtung bestätigt | Wird **Partner**: Ab jetzt bekommt sie automatisch **anonyme Profile** passender Kandidaten |
| Partner antwortet „INTERESSE K1001“ | Stellt **Kandidat und Arbeitgeber per E-Mail einander vor** (mit Telefonnummer) |
| „ABMELDEN“ / „STOP“ | Löscht die Person, bestätigt |
| Fragen, Beschwerden, Verhandlungen, Unklares | Sammelt sie für dich |
| Einmal täglich | **Tagesbericht an dich**: Zahlen, Erledigtes, offene Fragen, **Anrufliste** (passende Stellen aus der Jobbörse, bei denen du anrufen solltest), Kennenlernen → Rechnung stellen |

## Was er bewusst **nicht** macht (rechtliche Leitplanken)
- **Keine Kalt-Mails an Firmen.** Werbe-E-Mails ohne Einwilligung sind in Deutschland auch an Firmen verboten (§ 7 UWG). Deshalb landen fremde Einrichtungen auf deiner **Anrufliste**. Ein Anruf bei Firmen ist bei mutmaßlichem Interesse erlaubt. Sobald die Einrichtung uns eine Mail schreibt, übernimmt der Mitarbeiter.
- **Keine Kandidatendaten ohne Zustimmung**, und Name/Telefon erst beim Kennenlernen.
- **Keine Verträge und Rechnungen.** Das machst du selbst, wenn im Bericht „KENNENLERNEN“ steht (ca. 1×/Woche).
- Kundendaten liegen **verschlüsselt** im Repo (`data/crm.enc`). Ohne `CRM_KEY` kann sie niemand lesen.

## Einrichtung (ca. 30 Minuten, kostenlos)
1. **Neues Gmail-Konto** für die Firma anlegen, 2-Faktor-Anmeldung aktivieren und ein **App-Passwort** erstellen (Google-Konto → Sicherheit → App-Passwörter).
2. **Formular**: Bei [formsubmit.co](https://formsubmit.co) oder Formspree (beide kostenlos) die Gmail-Adresse als Ziel nutzen. Die Formular-URL in `config.json` → `formular_endpoint` eintragen.
3. Schlüssel erzeugen: `python -m mitarbeiter.schluessel`
4. GitHub → Settings → Secrets and variables → Actions → **Secrets**:
   - `MAIL_USER` = Gmail-Adresse, `MAIL_PASS` = App-Passwort
   - `INHABER_EMAIL` = **deine private** Adresse (für den Tagesbericht)
   - `CRM_KEY` = Schlüssel aus Schritt 3 (**gut aufbewahren!** Ohne ihn sind die Daten weg)
   - optional `ANTHROPIC_API_KEY` (siehe unten)
5. Optional unter **Variables**: `ABSENDER_NAME`, `HONORAR_TEXT`, `CLAUDE_MODELL`, `BERICHT_STUNDE_UTC` (Standard 6 = 7 Uhr MEZ).
6. Branch nach `main` mergen. Ab dann läuft alles stündlich. Testen: Actions → „Digitaler Mitarbeiter“ → *Run workflow* mit „Tagesbericht sofort senden“.

## KI: mit oder ohne?
- **Ohne API-Schlüssel (0 €):** Der Mitarbeiter arbeitet mit festen Regeln. Formularfelder und Schlüsselwörter (JA, EINVERSTANDEN, INTERESSE, ABMELDEN) versteht er zuverlässig. Freie Texte wie „Klingt gut, schicken Sie mir die Unterlagen“ landen bei dir im Bericht.
- **Mit Claude (`ANTHROPIC_API_KEY`):** Er versteht frei formulierte Mails, Rückfragen und Formular-E-Mails in jedem Format. Kosten: wenige Cent pro Mail mit dem Standardmodell `claude-opus-5-5`. Mit `CLAUDE_MODELL=claude-haiku-5-5` (Variable) ein Bruchteil davon. Fällt die KI aus, arbeitet er automatisch mit den Regeln weiter.

## Lokal testen (ohne Mails zu senden)
```
pip install -r requirements.txt
python -m unittest discover -s tests -t .     # simuliert Bewerbung → Zustimmung → Partner → Profil → Kennenlernen
python -m mitarbeiter.agent --trocken
```
