# KI-Sprint: 10.000 € in 7 Tagen

**Angebot:** Ein KI-Assistent für kleine Betriebe (Zahnärzte, Physios, Handwerker, Makler …). Er beantwortet Anfragen rund um die Uhr, bucht Termine ein und fasst automatisch nach.
**Preis:** 1.490 € / **2.490 €** / 3.900 € Festpreis.
**Ziel:** 4 × 2.490 € = 9.960 €, plus ein Upsell. Oder 3 × 3.900 €.

> Ehrlich: Das System findet Kunden, recherchiert sie, schreibt die Nachrichten, plant das Nachfassen und nimmt Zahlungen an.
> **Telefonieren und Abschließen musst du selbst.** Ob 10.000 € zusammenkommen, hängt davon ab, wie viele Kontakte du wirklich machst.

## Die Rechnung

| Schritt | Menge | Quote |
|---|---|---|
| Kontakte (Anrufe + Formulare + LinkedIn) | **300** | ~45 pro Tag |
| Gespräche / Interesse | 30 | ~10 % |
| Demo-Termine | 12 | ~40 % |
| Abschlüsse | **4** | ~33 % |

Anrufe wirken am stärksten, Formulare und LinkedIn ergänzen.

## Setup (30 Minuten)

```bash
cd ki-sprint
cp config.example.json config.json      # Name, Telefon, Buchungslink, Städte, Branchen eintragen
pip install anthropic                    # optional: KI-personalisierte Nachrichten
export ANTHROPIC_API_KEY=sk-ant-...      # optional
```

1. **Stripe:** Dashboard → Payment Links → 3 Links anlegen (1.490 / 2.490 / 3.900 €). In `landingpage/index.html` bei `ANPASSEN` eintragen.
2. **Buchungslink:** Kostenlos bei Cal.com oder Calendly einen 15-Minuten-Termin anlegen.
3. **Landingpage online stellen:** Den Ordner `landingpage/` auf Netlify Drop, Vercel oder GitHub Pages ziehen. Impressum und Datenschutz ergänzen, das ist in Deutschland Pflicht.

## Täglich laufen lassen

```bash
python sprint.py leads        # Firmen holen (OpenStreetMap, öffentlich)
python sprint.py analyze      # Websites prüfen → Score (je höher, desto heißer)
python sprint.py messages     # persönliche Nachricht + Telefonskript pro Firma
python sprint.py todo --voll  # Tagesliste: wen anrufen, wem schreiben, wen nachfassen
python sprint.py mark 17 kontaktiert             # nach jedem Kontakt
python sprint.py mark 17 termin --notiz "Do 14 Uhr"
python sprint.py mark 17 gewonnen --umsatz 2490
python sprint.py stats        # Funnel + Fortschritt zum 10.000-€-Ziel
python sprint.py dashboard    # dashboard.html im Browser öffnen
```

Nachfassen wird automatisch eingeplant: 3 Tage nach dem Erstkontakt, dann noch einmal nach 4 Tagen.

## 7-Tage-Plan

| Tag | Aufgabe |
|---|---|
| **Mo** | Setup, Stripe-Links, Landingpage live. `leads` + `analyze` + `messages`. **Erste 30 Anrufe** am Nachmittag. |
| **Di** | 50 Kontakte (Anrufe 9–11 und 14–16 Uhr, dazwischen Formulare und LinkedIn). Erste Demos legen. |
| **Mi** | 50 Kontakte + Demos. Nach jeder Demo **sofort den Stripe-Link schicken**, nicht erst ein PDF-Angebot. |
| **Do** | 50 Kontakte + Nachfassen (`todo`). Die ersten Kunden einrichten (siehe unten). |
| **Fr** | 50 Kontakte + Nachfassen. Bonus-Angebot: „Wer bis Sonntag bucht, bekommt WhatsApp gratis dazu.“ |
| **Sa** | Kunden einrichten. Formulare und LinkedIn-Nachrichten verschicken. |
| **So** | Letztes Nachfassen bei allen heißen Leads. Ziel abrechnen. |

**In der Demo** (15 Minuten): (1) Fragen: „Wie viele Anrufe verpassen Sie pro Woche? Was ist ein Kunde wert?“ (2) Die Rechnung zeigen: 5 verpasste × 200 € = 1.000 € pro Woche verloren. (3) Ein Live-Beispiel zeigen. (4) „Soll ich Ihnen den Link schicken, dann starten wir Montag?“

## Was du lieferst (Tool-Stack, ca. 1 Tag pro Kunde)

- **Website-Chat mit KI:** Tidio Lyro, Userlike oder Chatbase, gefüttert mit FAQs, Leistungen und Preisen des Kunden
- **Terminbuchung:** Cal.com, Calendly, bei Ärzten Doctolib. Dazu Erinnerungen per SMS oder E-Mail.
- **Nachfassen und Weiterleitung:** n8n oder Make. Neue Anfrage → Antwort → Kalender → Erinnerung.
- **Telefon (Premium):** KI-Telefonassistent wie Fonio oder Synthflow, mit Weiterleitung an die Praxis

Halte die Kundenkonten **auf den Namen des Kunden**, so bleiben die laufenden Kosten beim Kunden.

## Rechtliches (wichtig!)

- **Keine Massen-Kalt-E-Mails.** Nach § 7 UWG sind Werbe-E-Mails ohne Einwilligung auch an Firmen unzulässig und können abgemahnt werden.
- **Anrufe bei Gewerbetreibenden** sind bei mutmaßlichem Interesse erlaubt. Ein Bezug zur Firma ist hier gegeben, aber nicht nachbohren, wenn jemand Nein sagt.
- **Kontaktformulare und LinkedIn:** einzeln und persönlich, kein Spam.
- Leads mit `mark ID verloren --notiz "kein Kontakt gewünscht"` markieren und nie wieder anschreiben.
- Gewerbe, Impressum, Datenschutz und Rechnung mit USt. (bzw. Kleinunternehmer-Hinweis) vorbereiten.
