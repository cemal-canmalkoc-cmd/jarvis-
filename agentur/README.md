# Deine KI-Werbeagentur

Eine Werbeagentur für **lokale Betriebe** (Handwerk, Praxen, Gastro, Dienstleister). Claude erledigt die Agentur-Arbeit:
Strategie, Google-Anzeigen, Meta-Anzeigen, Social-Media-Posts für 30 Tage, Landingpages und Monatsberichte.
Pro Kunde brauchst du dafür **etwa 1–2 Stunden im Monat** statt 2–3 Tage.

| Ordner/Datei | Wozu |
|---|---|
| `website/index.html` | Deine Agentur-Website mit 3 Paketen und Stripe-Links |
| `server.py` | **Vollautomatischer Betrieb:** Zahlung → Fragebogen → Produktion → Kundenportal → Monatslieferung |
| `agentur.py` | Produziert die komplette Kunden-Lieferung (auch manuell nutzbar) |
| `kunden/*.json` | Ein Briefing pro Kunde (Beispiel: `beispiel-baeckerei.json`) |
| `../ki-sprint/` | Kundengewinnung: findet Betriebe, schreibt Nachrichten, plant das Nachfassen |

## Geschäftsmodell

| Paket | Monatlich | Einrichtung | Inhalt |
|---|---|---|---|
| Start | 690 € | 490 € | 12 Posts/Monat, Google-Profil, Bericht |
| **Wachstum** | **1.290 €** | 490 € | 20 Posts, Google- und Meta-Anzeigen, Tracking |
| Komplett | 2.490 € | 990 € | 30 Posts, Anzeigen, Landingpage, Strategie-Call |

**Rechenbeispiel:** 6 Kunden „Wachstum“ = 6 × (1.290 + 490) = **10.680 € im ersten Monat**, danach **7.740 €/Monat wiederkehrend**.
Das ist der große Vorteil gegenüber Einmal-Projekten: Jeder neue Kunde zahlt jeden Monat.

> Ehrlich: Die Produktion läuft automatisch. **Den Verkauf nicht.** Kunden musst du gewinnen, entweder selbst per Telefon
> oder über einen Vertriebler auf Provision (siehe unten). Realistisch dauert das erste Kundenpaket 2–4 Wochen, nicht 7 Tage.

## Einrichtung (1 Stunde)

```bash
cd agentur
cp config.example.json config.json   # Agenturname, Kontakt, Stripe-Links
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

1. **Stripe:** Für jedes Paket ein Abo-Produkt (monatlich) plus die Einrichtungsgebühr als einmaligen Posten anlegen. Daraus Payment Links erstellen und in `website/index.html` bei `ANPASSEN` eintragen.
2. **Fragebogen:** In Tally oder Google Forms die Felder aus `kunden/beispiel-baeckerei.json` abfragen. In Stripe als Weiterleitung nach der Zahlung eintragen. So bekommt jeder Kunde nach dem Kauf automatisch den Fragebogen.
3. **Website online stellen:** Den Ordner `website/` auf Netlify Drop oder Vercel ziehen, dazu Impressum und Datenschutz.

## Ablauf pro Kunde

```bash
python agentur.py neu "Elektro Huber"            # Briefing anlegen → mit den Antworten aus dem Fragebogen füllen
python agentur.py produzieren elektro-huber      # → lieferungen/elektro-huber/2026-11/
python agentur.py rechnung elektro-huber --erstmonat
```

Die Lieferung enthält:
- `1_strategie.md`: Positionierung, Zielgruppen, Budgetverteilung, Plan für die ersten 30 Tage
- `2_google_ads.csv`: zum Import in den **Google Ads Editor**. Titel über 30 und Beschreibungen über 90 Zeichen werden automatisch aussortiert.
- `3_meta_ads.md`: 3 Anzeigenvarianten für den Werbeanzeigenmanager
- `4_social_redaktionsplan.csv`: Posts für 30 Tage. Per CSV-Import in Buffer, Later oder die Meta Business Suite einplanen.
- `5_landingpage.html` (Paket Komplett): fertige Seite, nur noch hochladen

**Jeden Monat:**
```bash
python agentur.py alle                                # neue Inhalte für alle Kunden
python agentur.py bericht elektro-huber zahlen.csv    # Monatsbericht (Spalten: kanal;ausgaben;impressionen;klicks;conversions)
```

**Wichtig:** Vor der Veröffentlichung jede Lieferung kurz durchsehen und vom Kunden freigeben lassen, besonders Preise, Öffnungszeiten und Aussagen über Leistungen. Das kostet 10 Minuten und schützt dich vor Haftungsärger.

## Vollautomatischer Betrieb (`server.py`)

Der Server wickelt das Tagesgeschäft ohne dich ab:

```
Kunde kauft auf der Website (Stripe)
  → automatische Willkommens-Mail mit Fragebogen-Link
  → Kunde füllt den Fragebogen aus
  → Claude produziert Strategie, Anzeigen, Posts und Landingpage
  → Mail: „Ihre Inhalte sind fertig“ → Kundenportal
  → Kunde gibt frei oder wünscht Änderungen (2 automatische Überarbeitungen pro Monat)
  → jeden Monat bei Zahlungseingang: neue Lieferung automatisch
  → bei Kündigung: Produktion stoppt
```

Dein Job: einmal am Tag `/admin?pw=…` öffnen (Kunden, Monatsumsatz, Protokoll). Bei Fehlern kommt eine Mail.

### Online stellen (ca. 1 Stunde, ab ~6 €/Monat)

1. **Server:** z. B. Hetzner Cloud (CX22) oder Render.com. Wichtig ist eine **dauerhafte Festplatte** für `agentur.db`, `kunden/` und `lieferungen/`.
   ```bash
   git clone <dein-repo> && cd jarvis-/agentur
   pip install -r requirements.txt
   cp config.example.json config.json   # ausfüllen, siehe unten
   export ANTHROPIC_API_KEY=sk-ant-...
   gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 server:app
   ```
   Davor gehört ein HTTPS-Proxy, am einfachsten **Caddy** mit `deine-agentur.de { reverse_proxy localhost:8000 }`. Mit einer systemd-Unit startet der Server nach einem Neustart automatisch.
   Nur **einen** Worker verwenden (`-w 1`), weil die Produktion im Hintergrund-Thread läuft.
2. **Stripe:**
   - 3 Abo-Produkte plus Einrichtungsgebühr anlegen und daraus Payment Links erstellen. Die Links kommen in `website/index.html`, die IDs `plink_…` in `config.json` → `payment_links`.
   - Unter Developers → Webhooks einen Endpoint `https://deine-agentur.de/webhook/stripe` mit den Events `checkout.session.completed`, `invoice.paid` und `customer.subscription.deleted` anlegen. Das Signing Secret kommt nach `stripe_webhook_secret`.
   - Im Kundenportal von Stripe die Selbst-Kündigung aktivieren, dann braucht auch die Kündigung dich nicht.
3. **E-Mail:** Die SMTP-Daten deines Mail-Anbieters (z. B. IONOS, Strato, Google Workspace) unter `smtp` eintragen.
4. **Testen:** `"testmodus": true` setzen, dann
   `curl -X POST -d "email=du@example.com&paket=komplett" https://deine-agentur.de/test/kauf` aufrufen und den Ablauf einmal selbst durchklicken. Danach den Testmodus wieder ausschalten.

### Was weiterhin nicht automatisch läuft (ehrlich)

- **Veröffentlichen:** Die Inhalte werden fertig geliefert, als Import-Dateien für Google Ads und als CSV für Buffer, Later oder die Meta Business Suite. Direkt in die Konten der Kunden posten geht nur mit eigenen API-Freigaben von Meta und Google, und die brauchen Wochen. Bis dahin: Pakete als „Inhalte & Anzeigen fertig zum Einspielen“ verkaufen, oder einen Freelancer für etwa 30 € pro Kunde und Monat einspielen lassen.
- **Neukunden:** Die Website verkauft selbst, aber jemand muss Besucher hinschicken. Möglich sind Google-Anzeigen für die eigene Agentur (Budget nötig), `ki-sprint` mit einem Vertriebler auf Provision (siehe unten) oder Empfehlungen.
- **Qualitätskontrolle:** Der Kunde gibt jede Lieferung selbst frei, bevor etwas live geht. Trotzdem gelegentlich Stichproben im Admin machen.

## Kunden gewinnen mit ki-sprint

In `../ki-sprint/config.json` das Angebot auf die Agentur umstellen:

```json
"angebot_satz": "Ich betreue lokale Betriebe bei Google-Anzeigen und Social Media: Sie bekommen mehr Anfragen aus Ihrer Stadt, monatlich kündbar und mit klarem Bericht, was es gebracht hat.",
"angebot_telefon": "Ich sorge dafür, dass {branche}-Betriebe bei Google ganz oben stehen, wenn jemand in der Stadt sucht.",
"buchungslink": "https://cal.com/DEIN-NAME/15min"
```

Danach wie gewohnt: `python sprint.py leads && python sprint.py analyze && python sprint.py messages && python sprint.py todo --voll`

### Ohne dich verkaufen: Vertriebler auf Provision

Damit es ohne dich läuft, gib die Tagesliste (`python sprint.py todo --voll` oder `export`) an einen freien Telefon-Vertriebler.
Faire Provision: **eine Monatsgebühr pro Abschluss** (z. B. 1.290 €) oder 20 % der ersten 3 Monate. Du zahlst also nur, wenn wirklich verkauft wurde.
Vertriebler findest du bei Freelancermap, Malt und Indeed oder in Vertriebs-Gruppen auf LinkedIn. Suchbegriff: „freier Handelsvertreter B2B, Provision“.
Den Vertrag als Handelsvertretervertrag nach § 84 HGB aufsetzen.

## Rechtliches

- **Keine Kalt-E-Mails** an Firmen (§ 7 UWG). Telefon bei mutmaßlichem Interesse, Kontaktformular und LinkedIn sind einzeln und persönlich in Ordnung.
- Bei Ärzten und Heilberufen gilt das **Heilmittelwerbegesetz**. Der Prompt beachtet es, trotzdem jede Lieferung prüfen.
- Werbekonten laufen **auf den Namen des Kunden**, und das Budget zahlt der Kunde direkt.
- Einen Auftragsverarbeitungsvertrag (AVV) mit den Kunden schließen, weil du Zugriff auf ihre Konten hast.
