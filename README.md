# Jarvis: autonomer Recruiting-Assistent von Hansa Personal (Gesundheitswesen Schweiz)

Jarvis arbeitet wie dein bester Mitarbeiter in der Personalvermittlung:

- **Findet Kandidaten:** Bewerbungsformular, WhatsApp, E-Mail-Postfach, Lebenslauf-Ordner und öffentliche Stellengesuche im Web
- **Prüft sie:** liest Diplom/Urkunde, Deutsch (B2), SRK-/MEBEKO-Stand und Bereich aus und bewertet mit A/B/C/X
- **Chattet selbst** per WhatsApp mit Kandidaten, fragt fehlende Angaben nach und nimmt Lebensläufe entgegen
- **Findet Kliniken** mit offenen Stellen und **ordnet Kandidaten passenden Kliniken zu**
- **Stellt Kandidaten anonym vor** (E-Mail an die Klinik, nach Zusage des Kandidaten)
- **Fasst nach**, wenn sich jemand drei Tage nicht meldet
- **Optional telefoniert er selbst** (KI-Telefonate). Ohne Telefonie bekommst du jeden Morgen deine Anrufliste mit Gesprächsleitfaden.
- **Wird von dir gesteuert:** per WhatsApp, iPhone-App oder Siri

## Was es kostet

| Baustein | Kosten | Wie |
|---|---|---|
| Server | **kostenlos** | Oracle Cloud „Always Free" (oder eigener PC) |
| Internetadresse + HTTPS | **kostenlos** | duckdns.org + automatisches Zertifikat |
| iPhone-App + Siri | **kostenlos** | läuft auf deinem Server |
| WhatsApp: deine Befehle, Antworten an Kandidaten | **kostenlos** | Meta Cloud API: Gespräche, die der andere beginnt, kosten nichts |
| WhatsApp-Erstkontakt per Vorlage | wenige Rappen pro Nachricht | optional; Formular-Bewerber schreiben dich selbst an |
| E-Mails an Kliniken | **kostenlos** | dein bestehendes Postfach |
| Eigene Anrufe mit Leitfaden | **kostenlos** | über dein Handy aus der App |
| **KI (Claude)** | **ca. 1 Fr. pro Tag** (geschätzt) | Sparmodus mit Claude Haiku 5.5; fast alles davon ist die tägliche Web-Suche |
| KI-Telefonate (Jarvis ruft selbst an) | pro Gesprächsminute | **optional**, über Twilio |

**Spar-Tipps:**
- `JARVIS_WEB_SEARCHES=2` reduziert die Web-Suche.
- Ganz ohne Web-Suche (nur Formular, WhatsApp und E-Mail) liegt die KI bei wenigen Rappen pro Tag.
- Mehr Qualität für mehr Geld: `JARVIS_SPARMODUS=0` nutzt Claude Opus 5.5.

## Bestandskunden & Honorare

**Kunden anlegen** – einfach per WhatsApp, auch mehrere auf einmal:
> Neue Kunden: Spital Muster AG, Zürich, hr@muster.ch, Frau Huber, sucht 2 Dipl. Pflegefachpersonen Psychiatrie 80–100 %.
> Pflegeheim Sonne, Bern, jobs@sonne.ch, sucht FaGe Langzeitpflege.

Danach liefert Jarvis automatisch: Sobald ein passender Kandidat Interesse bestätigt, bekommt der
Kunde ein anonymes Kurzprofil per E-Mail (jeder Kandidat nur einmal pro Kunde) und du eine 📦-Meldung.
Offene Kundenaufträge sucht Jarvis jeden Morgen **zuerst**. Abschalten: `JARVIS_AUTO_DELIVER=0`.

**Honorare festlegen** – Jarvis nennt nur, was du hinterlegst, und erfindet nie Preise:
> Pflege: 18 % vom Jahreslohn, 3 Monate Garantie
> FaGe: pauschal 6500 Franken, 3 Monate Garantie
> Arzt: 20 % vom Jahreslohn, 6 Monate Garantie

Die Honorare stehen in neuen Angeboten an Kliniken und im Telefonleitfaden (nur wenn gefragt). Bei Kunden
schreibt Jarvis „Es gelten die mit Ihnen vereinbarten Konditionen“.
Ohne hinterlegte Preise verweist Jarvis auf ein persönliches Angebot von dir.

> ⚖️ **Rechtliches Modell:** Hansa Personal findet und qualifiziert Kandidaten und liefert sie an
> **Schweizer Partner-Personalvermittler mit Bewilligung**. Die Partner vermitteln an die Arbeitgeber.
> Jarvis ist darauf eingestellt:
> - keine Akquise-Anrufe bei Arbeitgebern
> - Anfragen von Arbeitgebern werden als Lead weitergegeben
> - Kandidaten willigen im Formular in die Weitergabe an Partner ein
> - Kandidaten zahlen nie etwas
>
> Damit das sauber ist, bitte vor dem Start erledigen:
> 1. **Bewilligung jedes Partners prüfen.** Er braucht die kantonale Bewilligung und, weil die Kandidaten aus dem Ausland kommen,
>    die **SECO-Bewilligung für Auslandsvermittlung**. Das öffentliche Verzeichnis findet sich auf www.avg-seco.admin.ch.
> 2. **Schriftliche Kooperationsvereinbarung** mit jedem Partner abschliessen: Rollen, Honorarteilung, Datenschutz und
>    die Regel, dass Hansa keine eigenen Verträge mit Arbeitgebern schliesst.
> 3. **Gewerbeanmeldung** in Deutschland (private Arbeitsvermittlung ist dort erlaubnisfrei, aber anmeldepflichtig).
> 4. **Datenschutzerklärung** (DSGVO/nDSG) verlinken. Darin muss die Weitergabe an Schweizer Partner stehen.
> 5. **Kurz absichern lassen.** Ob reines Zuliefern von Kandidaten an einen Schweizer Vermittler selbst schon
>    bewilligungspflichtige Vermittlung ist, entscheidet im Einzelfall das kantonale Arbeitsamt bzw. das SECO.
>    Eine kurze schriftliche Anfrage dort (kostenlos) oder bei einer Anwältin bzw. einem Anwalt gibt euch Sicherheit.

## Was Jarvis sucht (`jarvis/config.py`)

**Pflege:** Dipl. Pflegefachpersonen (Akutspital, Psychiatrie, Geriatrie/Langzeitpflege) und FaGe.
Pflicht sind Urkunde und B2. Ausländische Diplome brauchen die SRK-Anerkennung. ⭐ = SRK-Anerkennung oder positiver Pre-Check.

**Ärzte:** Allg. Innere Medizin, Psychiatrie, Gynäkologie, Radiologie, Anästhesie, Geriatrie, Neurologie, Rehabilitation.
⭐ = MEBEKO-Anerkennung oder positiver Verfahrensstand.

## Tagesablauf (Autopilot)

| Zeit | Was Jarvis macht |
|---|---|
| 07:00 | Neue Bewerbungen prüfen, Web-Sourcing. Liegt er unter dem Tagesziel (20), sucht er in weiteren Regionen weiter. Bei Bedarf sucht er neue Kliniken. |
| 07:xx | **Morgenbericht an dein WhatsApp:** Top-Kandidaten, 🤝 Vermittlungsvorschläge, 🔁 Nachfassen, 📞 deine Anrufliste |
| sofort | Neue Bewerbungen und WhatsApp-Nachrichten werden direkt geprüft und beantwortet; heisse Kandidaten meldet er dir |
| Mo–Fr 9–18 Uhr | Erstkontakte per WhatsApp-Vorlage; mit Telefonie auch KI-Anrufe |

## Bedienung

### WhatsApp-Befehle (normale Sprache)
- „Tagesbericht"
- „Zeig mir die Top 10"
- „Welche Kliniken passen zu 3f2a1b?"
- „Stell 3f2a1b bei Firma 4 vor"
- „Wen muss ich nachfassen?"
- „Such Kliniken in Zürich, die Anästhesisten suchen"
- „Schreib ein Inserat für Facebook-Gruppen für Pflegefachfrauen aus Deutschland"
- „Die Klinik 4 hat die E-Mail hr@klinik.ch, Ansprechperson Frau Huber"

### 📱 iPhone-App
1. In **Safari** öffnen: `https://DEINE-ADRESSE/app`
2. Zugangscode eingeben (= `JARVIS_ADMIN_TOKEN`)
3. **Teilen → „Zum Home-Bildschirm"**

Die App hat vier Bereiche:
- **Heute:** Tagesziel und Zahlen
- **Kandidaten:** Details, 🤝 passende Kliniken mit „Vorstellen", 📝 Gesprächsleitfaden, 📞/💬 Knöpfe
- **Firmen**
- **Jarvis-Chat:** mit Sprache 🎤 und Vorlesen 🔊

### „Hey Siri, Jarvis"
1. App **Kurzbefehle** → **+** → Name: **Jarvis**
2. **„Text diktieren"** (Deutsch)
3. **„Inhalte von URL abrufen"**
   - URL: `https://DEINE-ADRESSE/api/befehl`
   - Methode **POST**
   - Header `Authorization` = `Bearer DEIN_ADMIN_TOKEN`
   - Hauptteil **JSON** mit `text` = *Diktierter Text* und `warten` = `25`
4. **„Wörterbuchwert abrufen"** → Schlüssel `antwort`
5. **„Text sprechen"**

Lange Aufträge (z.B. eine Web-Suche) meldet Jarvis per WhatsApp zurück.

## Einrichtung (kostenlos, ca. 1 Stunde)

### 1. Claude-Schlüssel
console.anthropic.com → Konto anlegen → Guthaben aufladen (im Sparmodus reichen wenige Franken lange) → API-Key erstellen.

### 2. Kostenloser Server (Oracle Cloud „Always Free")
1. Konto auf cloud.oracle.com anlegen. Für die Prüfung braucht es eine Kreditkarte, „Always Free"-Ressourcen werden aber nicht belastet.
2. VM erstellen: Ubuntu, Form **VM.Standard.A1.Flex** („Always Free eligible").
3. Im Netzwerk (Security List) die Ports **80** und **443** öffnen.
4. Auf der VM: `sudo apt install -y docker.io docker-compose-v2 git`

### 3. Kostenlose Adresse
Auf duckdns.org anmelden, eine Subdomain anlegen (z.B. `hansa-jarvis`) und die IP der VM eintragen.

### 4. WhatsApp (Meta, kostenlos)
1. business.facebook.com → Meta-Business-Konto (Firma Hansa Personal).
2. developers.facebook.com → App erstellen → Produkt **WhatsApp** hinzufügen.
3. Eine **eigene Nummer für Jarvis** registrieren. Das muss eine Nummer sein, die nicht schon in der normalen WhatsApp-App läuft, z.B. eine günstige Prepaid-SIM.
4. Einen **System-User-Token** erzeugen (dauerhaft) und die **Phone Number ID** notieren.
5. Webhook einrichten:
   - URL: `https://DEINE-ADRESSE/whatsapp`
   - Verify-Token: frei wählen, derselbe wie `META_VERIFY_TOKEN`
   - Feld **messages** abonnieren
6. Optional eine Erstkontakt-Vorlage einreichen, z.B.:
   > Grüezi {{1}}, hier ist Cemal-Can Malkoc von Hansa Personal. Wir haben passende Stellen für {{2}} in der Schweiz. Interesse an einem kurzen Gespräch? Antworten Sie mit JA – oder STOP, wenn Sie keine Nachrichten wünschen.

### 5. Starten
```bash
git clone <dieses Repo> jarvis && cd jarvis
cp .env.example .env && nano .env      # Werte eintragen
docker compose up -d
```
Test: Schreib Jarvis von deinem Handy „Tagesbericht".

### Optional: KI-Telefonate (kostenpflichtig)
Twilio-Konto anlegen, eine Schweizer Nummer kaufen (Regulatory Bundle nötig) und ConversationRelay aktivieren.
Dann `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` und `TWILIO_VOICE_FROM` in die `.env` eintragen.

## 📇 Welche Nummer wofür

| Nummer | Wofür | Einstellung |
|---|---|---|
| **+49 176 …** (deine) | Dein WhatsApp: Befehle an Jarvis, Berichte und 🔥-Meldungen von Jarvis | `JARVIS_OWNER_WHATSAPP` |
| **+49 151 28143836** | **Nur Telefon:** Kandidaten und Kliniken rufen an, Jarvis nimmt ab (Umleitung zu Twilio). Als Absender für Rückrufe nutzbar (Verified Caller ID). | `JARVIS_CALL_IN_NUMBER` |
| **Jarvis' WhatsApp** | Damit schreibt Jarvis automatisch an Kandidaten. Muss eine Nummer sein, die in **keiner** WhatsApp-App läuft. | `JARVIS_WHATSAPP_NUMBER` |

**Technische Grenzen:**
- Eine Nummer kann nicht gleichzeitig in deiner WhatsApp-App und bei Jarvis (WhatsApp Business API) laufen.
  Machst du deine 176 zur Jarvis-Nummer, verschwindet sie aus deiner WhatsApp-App. Dann steuerst du Jarvis
  über die iPhone-App und Siri, und Meldungen kommen in die App (Bereich „Meldungen") und per E-Mail (`JARVIS_OWNER_EMAIL`).
- Normale Telefonanrufe lassen sich nicht „auf WhatsApp umleiten". Jarvis nimmt Anrufe auf der 151 selbst an.
  Sagt die Person im Gespräch „WhatsApp ist ok", schreibt Jarvis ihr danach auf WhatsApp weiter (Lebenslauf anfordern).

## ☎️ Anrufe annehmen: Jarvis als Telefonzentrale (+49 151 28143836)

Kandidaten und Kliniken rufen **euch** an, und Jarvis nimmt ab. Das ist rechtlich die sauberste Lösung, denn wer
selbst anruft, hat zugestimmt. Die Nummer steht automatisch in WhatsApp-Nachrichten, im Formular, in
E-Mails und in Inseraten.

Was Jarvis am Telefon macht:
- **Kandidat ruft an:** fragt Beruf, Diplom, Deutsch, SRK/MEBEKO, Wohnort und Verfügbarkeit ab, legt das Profil an, bewertet es und
  liefert bei Interesse direkt an passende Kunden. Du bekommst ☎️🔥 per WhatsApp.
- **Klinik ruft an:** nimmt Firma, Ansprechperson, E-Mail und Bedarf auf, nennt eure Honorare (falls hinterlegt) und
  sagt deinen Rückruf zu. Du bekommst ☎️🏥🔥 mit der Rückrufnummer.
- **Bekannte Nummern** erkennt er (Kandidat oder Klinik) und spricht passend.

### Einrichtung
1. Bei Twilio eine **deutsche Nummer** kaufen (Regulatory Bundle nötig) und bei „A call comes in" eintragen:
   `https://DEINE-ADRESSE/voice/inbound` (POST).
2. Auf dem Handy mit der SIM **+49 151 28143836** eine Rufumleitung zu dieser Twilio-Nummer einrichten. Zwei Varianten:

**Variante A: Alle Anrufe gehen an Jarvis** (die Nummer ist nur für Jarvis):
`**21*+49TWILIONUMMER#` wählen und anrufen. Ausschalten mit `##21#`.

**Variante B: Du nimmst Bekannte selbst ab, Jarvis nimmt Unbekannte ab:**
- iPhone: Einstellungen → Apps → Telefon → **Unbekannte Anrufer stummschalten** einschalten
- Rufumleitung bei Nichtannahme, besetzt und nicht erreichbar zu Jarvis:
  `**61*+49TWILIONUMMER*11*15#`, `**67*+49TWILIONUMMER#`, `**62*+49TWILIONUMMER#`

Kontakte klingeln dann normal bei dir. Unbekannte Anrufer werden stummgeschaltet und landen statt auf der Mailbox bei Jarvis.

3. Optional: Die +49 151 … bei Twilio als **Verified Caller ID** bestätigen und als `TWILIO_VOICE_FROM` setzen.
   Dann sehen Angerufene eure Nummer, und Rückrufe landen wieder bei Jarvis.

**Kosten:** Das ist nicht gratis.
- Die Umleitung kostet je nach Handytarif; zu einer deutschen Nummer ist sie meist in der Flatrate.
- Dazu kommen Twilio-Gebühren pro Gesprächsminute (Nummer, Sprachdienst).
- Ohne Twilio geht die Telefonzentrale nicht. Alles andere läuft trotzdem.

## So kommst du auf 20+ vermittelbare Kandidaten pro Tag

1. **Formular verbreiten:** `https://DEINE-ADRESSE/bewerbung`
   - Lass Jarvis Inserate schreiben und poste sie in Facebook-Gruppen (Pflege Schweiz, Pflegekräfte Deutschland→Schweiz, Ärzte in der Schweiz), auf Instagram und in Jobportalen. Das kostet nichts und ist der stärkste Kanal.
   - Wer sich bewirbt, kann direkt per WhatsApp mit Jarvis chatten.
2. **Lebensläufe aus Portalen** mit Recruiter-Zugang nach `data/inbox/` legen.
3. **Bewerbungspostfach** per IMAP anbinden.
4. **Web-Sourcing** läuft jeden Morgen automatisch.

## Fest eingebaute Leitplanken

| Regel | Warum |
|---|---|
| Jarvis sagt, dass er ein KI-Assistent ist | EU AI Act (Transparenzpflicht) |
| Automatische Anrufe/WhatsApps an Kandidaten nur mit Einwilligung | UWG (CH) / §7 UWG (DE), WhatsApp-Richtlinien |
| Web-Funde ohne Einwilligung: nur ein Link für dich zum manuellen Kontakt | Datenschutz (nDSG/DSGVO) |
| „STOP" → Sperrliste, nie wieder Kontakt | nDSG/DSGVO, UWG |
| Vorstellung bei Kliniken nur anonym und erst nach Zusage des Kandidaten | Datenschutz, Vertrauen |
| Anrufe nur Mo–Fr 9–18 Uhr | Seriosität |
| Kein Scraping von LinkedIn/XING | Nutzungsbedingungen |

## Aufbau

```
jarvis/
  config.py      Bedarf, Einstellungen, Sparmodus
  brain.py       Claude: Profile auslesen, Stellengesuche finden
  scoring.py     Bewertung A/B/C/X
  pipeline.py    Sammeln → Prüfen → Speichern → Shortlist
  matching.py    Kandidat ↔ Klinik, Kunden beliefern, Nachfassen
  pricing.py     Honorare je Bereich
  companies.py   Kliniken finden
  agent.py       WhatsApp/App/Siri-Befehle + Kandidaten-Chat
  messaging.py   WhatsApp (Meta oder Twilio)
  voice.py       KI-Telefonate (optional)
  autopilot.py   Tagesablauf
  server.py      Formular, Webhooks
  mobile.py      iPhone-App + Siri
  store.py       Datenbank (SQLite)
```

## Tests

```bash
python -m pytest -q     # 51 Tests, simuliert Claude/WhatsApp/Telefon – keine echten Kosten
```
