# Heute live, 0 € Kosten (ca. 90 Minuten)

Alles hier ist kostenlos. Geld fließt nur in eine Richtung: von Kunden zu dir.
Die einzigen Abzüge sind die Stripe-Gebühren pro Zahlung (ca. 1,5 % + 0,25 €), und die zahlst du aus dem Umsatz.

| Baustein | Dienst | Kosten |
|---|---|---|
| Website | Netlify Drop | 0 € |
| Zahlung und Abos | Stripe | 0 € Grundgebühr |
| Fragebogen nach dem Kauf | Tally | 0 € |
| Gesprächstermine | Cal.com | 0 € |
| Inhalte erstellen | claude.ai Free-Plan + `PROMPTS.md` | 0 € |
| Kunden finden | `../../ki-sprint` (OpenStreetMap, ohne KI: `--ohne-ki`) | 0 € |
| E-Mail | dein Gmail-Konto | 0 € |

## Schritt 1: Stripe (20 Min.)
1. https://dashboard.stripe.com/register → Konto anlegen und Gewerbe-Daten sowie Bankkonto hinterlegen.
2. **Produktkatalog → Produkt hinzufügen**, 3 Mal:
   - „Paket Start“: 690 €, **wiederkehrend monatlich**
   - „Paket Wachstum“: 1.290 €, wiederkehrend monatlich
   - „Paket Komplett“: 2.490 €, wiederkehrend monatlich
   - zusätzlich einmalig „Einrichtung“: 490 € bzw. 990 €
3. **Payment Links → Neu:** je Paket das Abo plus die passende Einrichtung als einmaligen Posten.
   Unter **„Nach der Zahlung“** die Option **„Kunden auf deine Website weiterleiten“** wählen und dort den Tally-Link aus Schritt 2 eintragen.
4. **Einstellungen → Billing → Kundenportal** aktivieren. Dann können Kunden selbst kündigen, ohne dich.

## Schritt 2: Tally-Fragebogen (15 Min.)
1. https://tally.so → kostenlos registrieren → neues Formular.
2. Diese Fragen anlegen:
   Name des Betriebs · E-Mail · Branche · Ort/Einzugsgebiet · Website · wichtigste Leistungen · ideale Kunden ·
   Was unterscheidet Sie? · Ziel der Werbung · aktuelle Aktion · Wie sollen Kunden Sie kontaktieren? ·
   Tonalität · Werbebudget pro Monat · Was dürfen wir nicht sagen? · gebuchtes Paket (Auswahl)
3. Unter Einstellungen → **Benachrichtigungen per E-Mail** an dich einschalten.
   Dann bekommst du jedes ausgefüllte Briefing sofort ins Postfach.

## Schritt 3: Cal.com (5 Min.)
https://cal.com → kostenlos registrieren → Termin „15-Min-Analyse“ anlegen und mit deinem Google-Kalender verbinden.

## Schritt 4: Website online (10 Min.)
```bash
cd agentur
cp kostenlos/daten.example.json kostenlos/daten.json   # Name, Adresse, Links eintragen
python kostenlos/website_bauen.py
```
- Datenschutzerklärung kostenlos erstellen: https://www.e-recht24.de/muster-datenschutzerklaerung.html, als `kostenlos/datenschutz.html` speichern und das Skript erneut ausführen.
- Den Ordner `kostenlos/fertig` auf **https://app.netlify.com/drop** ziehen. Die Website ist sofort online.
  Mit einem kostenlosen Netlify-Konto bleibt sie dauerhaft online. Unter Site settings kannst du einen Namen wählen, z. B. `deinname-media.netlify.app`.

## Schritt 5: Heute noch Kunden ansprechen (Rest des Tages)
```bash
cd ki-sprint
cp config.example.json config.json   # Name, Telefon, Cal.com-Link, Netlify-Adresse, Stadt
```
In `config.json` noch das Agentur-Angebot ergänzen, siehe `agentur/README.md` → „Kunden gewinnen mit ki-sprint“. Dann:
```bash
python sprint.py leads && python sprint.py analyze && python sprint.py messages --ohne-ki
python sprint.py todo --voll
```
Anrufen, Kontaktformulare und LinkedIn nutzen. **Keine Massen-Mails** (§ 7 UWG).

## Wenn ein Kunde gekauft hat
1. Stripe schickt dir eine Mail („Zahlung erhalten“), Tally schickt dir das ausgefüllte Briefing.
2. Die Prompts aus `PROMPTS.md` in claude.ai ausführen, etwa 15 Minuten.
3. Die Ergebnisse als Google Doc an den Kunden schicken und um Freigabe bitten.
4. Jeden Monat bucht Stripe automatisch ab. Du führst Prompt E aus und schickst die neuen Inhalte.

## Später, wenn das erste Geld da ist
Dann lohnt sich die Vollautomatik (`server.py`, ca. 6 € pro Monat für den Server plus wenige Cent Claude-API pro Kunde).
Dabei fallen auch die 15 Minuten Handarbeit pro Kunde weg. Bezahlt wird das aus der ersten Kundenzahlung, nicht aus deiner Tasche.
