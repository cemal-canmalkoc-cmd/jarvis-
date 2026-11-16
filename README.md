# Jarvis: autonomer Recruiting-Assistent (Gesundheitswesen Schweiz)

Jarvis arbeitet selbstständig wie ein Personalvermittler:

- **Findet Kandidaten:** Bewerbungsformular, WhatsApp, E-Mail-Postfach, Lebenslauf-Ordner und öffentliche Stellengesuche im Web
- **Prüft sie:** Claude liest Diplom/Urkunde, Deutsch (B2), SRK-/MEBEKO-Stand und Bereich aus, danach bewertet Jarvis mit A/B/C/X
- **Telefoniert selbst:** ruft Kandidaten mit Einwilligung und Arbeitgeber an, führt das Gespräch live auf Deutsch und fasst es danach zusammen
- **Chattet selbst:** beantwortet WhatsApp-Nachrichten von Kandidaten, fragt fehlende Angaben nach und nimmt Lebensläufe als PDF an
- **Akquiriert Arbeitgeber:** sucht Spitäler, Kliniken und Heime mit offenen Stellen und bietet anonymisierte Kandidaten an
- **Wird von dir per WhatsApp, iPhone-App oder Siri gesteuert** und meldet sich bei dir mit Morgenbericht, heissen Kandidaten und Anrufergebnissen

## Was Jarvis sucht (`jarvis/config.py`)

**Pflege:** Dipl. Pflegefachpersonen (Akutspital, Psychiatrie, Geriatrie/Langzeitpflege) und FaGe.
Pflicht sind Urkunde und B2. Ausländische Diplome brauchen die SRK-Anerkennung. ⭐ = SRK-Anerkennung oder positiver Pre-Check.

**Ärzte:** Allg. Innere Medizin, Psychiatrie, Gynäkologie, Radiologie, Anästhesie, Geriatrie, Neurologie, Rehabilitation.
⭐ = MEBEKO-Anerkennung oder positiver Verfahrensstand.

## Tagesablauf (Autopilot)

| Zeit | Was Jarvis macht |
|---|---|
| 07:00 | Neue Bewerbungen prüfen, Web-Sourcing über alle Bereiche. Liegt er unter dem Tagesziel (20), sucht er in weiteren Regionen weiter. Bei Bedarf sucht er neue Arbeitgeber. |
| 07:xx | **Morgenbericht an dein WhatsApp** mit Top-Kandidaten und Link zur Shortlist |
| Mo–Fr 9–18 Uhr, stündlich | Kandidaten mit Einwilligung anrufen, WhatsApp-Erstkontakt per Vorlage, Arbeitgeber anrufen |
| sofort | Neue Bewerbung über das Formular mit Tier A/B: Jarvis ruft innerhalb von Minuten an |
| nach jedem Anruf | Zusammenfassung und nächster Schritt an dich, Status wird automatisch gesetzt |

## 📱 Bedienung am iPhone

### Jarvis-App auf dem Home-Bildschirm
1. In **Safari** öffnen: `https://DEINE-ADRESSE/app`
2. Zugangscode eingeben (= `JARVIS_ADMIN_TOKEN`). Du bleibst ein Jahr angemeldet.
3. **Teilen** (Quadrat mit Pfeil) → **„Zum Home-Bildschirm"** → Hinzufügen

Jetzt liegt Jarvis als App mit eigenem Symbol auf dem iPhone. Die App ist in vier Bereiche aufgeteilt:

| Tab | Inhalt |
|---|---|
| **Heute** | Fortschritt zum Tagesziel, Zahlen, Schnellbefehle, letzte Anrufe mit Zusammenfassung |
| **Kandidaten** | Liste mit Filtern (🔥 Interessiert, Tier A, Pflege, Ärzte). Antippen zeigt alle Details mit den Knöpfen **📞 Jarvis ruft an**, **💬 WhatsApp**, **☎️ Selbst anrufen** und Status setzen |
| **Firmen** | Arbeitgeber mit Bedarf; Jarvis anrufen lassen oder selbst anrufen |
| **Jarvis** | Chat mit Jarvis, gleicher Verlauf wie per WhatsApp. 🎤 Spracheingabe, 🔊 Antworten vorlesen lassen |

### „Hey Siri, Jarvis"
Mit einem Kurzbefehl sprichst du Jarvis direkt über Siri an, und Siri liest die Antwort vor.

1. App **Kurzbefehle** → **+** → Name: **Jarvis**
2. Aktion **„Text diktieren"** (Sprache: Deutsch)
3. Aktion **„Inhalte von URL abrufen"**
   - URL: `https://DEINE-ADRESSE/api/befehl`
   - Methode: **POST**
   - Header: `Authorization` = `Bearer DEIN_ADMIN_TOKEN`
   - Hauptteil: **JSON** mit `text` = *Diktierter Text* und `warten` = Zahl `25`
4. Aktion **„Wörterbuchwert abrufen"**, Schlüssel: `antwort`
5. Aktion **„Text sprechen"**, Eingabe: *Wörterbuchwert*

Danach sagst du z.B. **„Hey Siri, Jarvis"**, Siri fragt nach, und du antwortest: *„Ruf die besten drei Kandidaten an."*
Dauert ein Auftrag länger als 25 Sekunden (z.B. eine Web-Suche), sagt Siri „Ich arbeite daran" und das Ergebnis kommt per WhatsApp.

## Befehle per WhatsApp (normale Sprache)

- „Tagesbericht"
- „Zeig mir die Top 10"
- „Ruf die besten 5 Kandidaten an"
- „Ruf Kandidat 3f2a… an"
- „Such Pflegefachpersonen Psychiatrie in Bern"
- „Such Kliniken in Zürich, die Anästhesisten suchen, und ruf die ersten 3 an"
- „Schreib ein Inserat für Facebook-Gruppen für Pflegefachfrauen aus Deutschland"
- „Setz 3f2a… auf vermittelt"

Lokal testen geht ohne WhatsApp: `python -m jarvis befehl "Tagesbericht"`

## Einrichtung (einmalig)

### 1. Twilio-Konto (Telefon + WhatsApp)
1. Konto auf twilio.com anlegen und eine **Schweizer Telefonnummer** kaufen. Für CH-Nummern verlangt Twilio ein „Regulatory Bundle" (Firmenangaben).
2. **WhatsApp-Sender** registrieren (Twilio Console → Messaging → WhatsApp Senders). Dafür braucht es ein verifiziertes Meta-Business-Konto.
3. Eine **Vorlage für den Erstkontakt** anlegen und von Meta freigeben lassen (Content Template Builder), z.B.:
   > Grüezi {{1}}, hier ist das Recruiting-Team von [Agentur]. Wir haben passende Stellen für {{2}} in der Schweiz. Interesse an einem kurzen Gespräch? Antworten Sie mit JA – oder STOP, wenn Sie keine Nachrichten wünschen.

   Die Content-SID (beginnt mit `HX…`) kommt als `TWILIO_TEMPLATE_FIRST_CONTACT` in die `.env`.
4. **ConversationRelay** für Sprachanrufe aktivieren (Voice → Settings: AI-/Predictive-Features akzeptieren).

### 2. Server
Jarvis braucht einen Server mit öffentlicher HTTPS-Adresse, der dauerhaft läuft, z.B. Railway, Render, Fly.io oder ein eigener VPS.

```bash
docker build -t jarvis .
docker run -d --env-file .env -v jarvis-data:/data -p 8000:8000 --restart unless-stopped jarvis
```

Ohne Docker: `pip install -r requirements.txt && python -m jarvis serve`

**Wichtig:** Das Verzeichnis `/data` muss erhalten bleiben (persistentes Volume). Dort liegen alle Kandidaten.

### 3. `.env` ausfüllen
```bash
cp .env.example .env
```
Pflicht sind `ANTHROPIC_API_KEY`, `JARVIS_PUBLIC_URL`, `JARVIS_OWNER_WHATSAPP` (deine Handynummer), `JARVIS_ADMIN_TOKEN`
sowie die Twilio-Werte.

### 4. Webhooks bei Twilio eintragen
- WhatsApp-Sender → „A message comes in": `https://DEINE-ADRESSE/whatsapp` (POST)
- Die Anruf-Webhooks setzt Jarvis bei jedem Anruf selbst.

### 5. Testen
Schreib Jarvis von deinem Handy aus per WhatsApp „Tagesbericht". Er antwortet innerhalb weniger Sekunden.

## So kommst du auf 20+ vermittelbare Kandidaten pro Tag

Jarvis kann nur so viele Kandidaten finden, wie in die Pipeline fliessen. Die stärksten Hebel:

1. **Bewerbungsformular verbreiten:** `https://DEINE-ADRESSE/bewerbung`. Lass Jarvis Inserate schreiben („Inserat für …") und poste sie in Facebook-Gruppen (Pflege Schweiz, Pflegekräfte Deutschland→Schweiz, Ärzte in der Schweiz), auf Jobportalen und Instagram. Wer sich über das Formular bewirbt, darf sofort angerufen werden. Das ist der schnellste Kanal.
2. **Lebensläufe aus Portalen**, auf denen ihr einen Recruiter-Zugang habt, nach `data/inbox/` exportieren.
3. **Bewerbungspostfach** per IMAP anbinden.
4. **Web-Sourcing** läuft jeden Morgen automatisch und weitet die Suche aus, wenn das Ziel nicht erreicht ist.

## Fest eingebaute Leitplanken

Diese Regeln schützen deine Nummern vor Sperrung und dich vor Abmahnungen:

| Regel | Warum |
|---|---|
| Jarvis sagt im ersten Satz, dass er ein KI-Assistent ist | EU AI Act (Transparenzpflicht), Vertrauen |
| Automatische Anrufe an Kandidaten nur mit Einwilligung (Formular oder eigene Bewerbung) | UWG (CH) / §7 UWG (DE): Kaltakquise bei Privatpersonen ist unzulässig |
| Automatische WhatsApps nur mit Opt-in, Erstkontakt nur per freigegebener Vorlage | WhatsApp-Richtlinien, sonst Sperre der Nummer |
| Web-Funde ohne Einwilligung: nur ein WhatsApp-Link für dich zum manuellen Senden | Datenschutz (nDSG/DSGVO) |
| „STOP"/„kein Interesse" → Sperrliste, nie wieder Kontakt | nDSG/DSGVO, UWG |
| Anrufe nur Mo–Fr 9–18 Uhr, Anrufbeantworter → auflegen | Seriosität |
| Arbeitgeber mit „keine Personalvermittler" werden nicht angerufen | Ruf der Agentur |
| Kein Scraping von LinkedIn/XING | Nutzungsbedingungen |
| Kandidaten werden Arbeitgebern nur anonym vorgestellt | Datenschutz |

## Aufbau

```
jarvis/
  config.py      Bedarf, Einstellungen
  brain.py       Claude: Profile auslesen, Stellengesuche im Web finden
  scoring.py     Bewertung A/B/C/X (eure Regeln)
  pipeline.py    Sammeln → Prüfen → Speichern → Shortlist
  sources.py     Ordner, E-Mail
  companies.py   Arbeitgeber finden
  voice.py       KI-Telefonate (Twilio ConversationRelay + Claude)
  agent.py       WhatsApp: deine Befehle + Kandidaten-Chat
  autopilot.py   Tagesablauf
  server.py      Formular, Webhooks, Dashboard
  mobile.py      iPhone-App + Siri-Schnittstelle
  static/        App-Oberfläche und Symbol
  store.py       Datenbank (SQLite)
```

## Tests

```bash
python -m pytest -q     # 28 Tests, simuliert Claude und Twilio – keine echten Anrufe
```
