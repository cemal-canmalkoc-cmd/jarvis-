# Kopier-Prompts für claude.ai (kostenloser Plan)

So gehst du pro Kunde vor, etwa 15 Minuten:
1. Auf https://claude.ai einen **neuen Chat** öffnen.
2. Prompt A kopieren. Bei `[BRIEFING]` die Antworten aus dem Tally-Fragebogen des Kunden einfügen. Abschicken.
3. Im selben Chat Prompt B schicken, danach C (nur Paket Komplett).
4. Die Ergebnisse in ein Google Doc kopieren und dem Kunden mit der Bitte um Freigabe schicken. Antwortet er mit Änderungswünschen, diese einfach in den Chat schreiben.

Tipp: Lege auf claude.ai ein **Projekt „Agentur“** an und speichere die Grundregeln unten als Projekt-Anweisungen. Dann musst du sie nicht jedes Mal mitkopieren.

---

## Grundregeln (einmal als Projekt-Anweisung speichern oder vor Prompt A einfügen)

```
Du bist Senior-Performance-Marketer und Texter einer deutschen Werbeagentur für lokale Betriebe.
Du schreibst konkret, lokal und verkaufsstark, ohne leere Floskeln.
Halte dich an deutsches Werberecht: keine unbelegten Superlative ("der Beste", "Nr. 1"), keine Heilversprechen,
bei Ärzten/Heilberufen das Heilmittelwerbegesetz beachten, keine erfundenen Bewertungen, Zahlen oder Auszeichnungen.
Nutze nur Fakten aus dem Briefing. Fehlt etwas, formuliere neutral statt zu erfinden.
```

## Prompt A: Strategie und Anzeigen

```
Erstelle für diesen Kunden das Monatspaket, Teil 1.

BRIEFING:
[BRIEFING]

Liefere, klar mit Überschriften gegliedert:
1. STRATEGIE: Positionierung (2 Sätze), Kernbotschaft, 2–4 Zielgruppen-Segmente, Verteilung des Werbebudgets auf die Kanäle, 3–5 KPIs, konkrete Schritte für die ersten 30 Tage.
2. GOOGLE ADS (lokale Suchkampagne):
   - 15–25 Keywords mit Ortsbezug
   - 10 ausschließende Keywords
   - genau 15 Anzeigentitel, JEDER MAXIMAL 30 ZEICHEN (Zeichenzahl in Klammern dahinter)
   - genau 4 Beschreibungen, JEDE MAXIMAL 90 ZEICHEN (Zeichenzahl in Klammern dahinter)
   - 4 Sitelinks (max. 25 Zeichen)
3. META ADS: 3 Anzeigenvarianten (Winkel: Angebot / Vertrauen & Geschichte / Problem & Lösung), je mit Zielgruppe, Primärtext, Überschrift, Button und einer Bildidee, die der Kunde selbst mit dem Handy fotografieren kann.
```

## Prompt B: Social-Media-Plan für 30 Tage

```
Jetzt Teil 2: ein Social-Media-Redaktionsplan für 30 Tage mit [ANZAHL: 12 / 20 / 30] Posts für Instagram, Facebook und das Google-Unternehmensprofil.
Als Tabelle mit den Spalten: Tag | Kanal | Format (Bild/Karussell/Reel) | Thema | fertiger Posttext mit Call-to-Action | Hashtags (3–8, inkl. lokaler) | Bildidee (selbst fotografierbar).
Abwechslung: Einblicke hinter die Kulissen, Leistungen, Tipps für Kunden, Team, Aktion, Saisonales.
```
(Bricht die Tabelle ab, schreibe einfach „weiter“.)

## Prompt C: Landingpage (nur Paket Komplett)

```
Jetzt Teil 3: Schreibe eine komplette, moderne Landingpage als EINE HTML-Datei (CSS inline, mobil optimiert, Dark Mode über prefers-color-scheme,
keine externen Bilder, sondern Farbflächen mit Bildbeschreibung). Abschnitte: Hero mit klarer Aktion, Leistungen, Warum wir (nur Fakten aus dem Briefing),
Ablauf/Bestellung, FAQ (4 Fragen), Kontakt, Footer mit den Links „Impressum“ und „Datenschutz“. Keine erfundenen Bewertungen.
Gib nur den HTML-Code aus.
```
Den Code in eine Datei `index.html` speichern und auf https://app.netlify.com/drop ziehen. Fertig ist die Kundenseite, ebenfalls kostenlos.

## Prompt D: Monatsbericht

```
Schreibe für [FIRMA] eine kurze, ehrliche Monatsauswertung (max. 150 Wörter, Sie-Form, 3 Absätze: Was lief gut, was verbessern wir, nächste Schritte).
Ziel des Kunden: [ZIEL]. Zahlen: [Ausgaben, Klicks, Anfragen je Kanal aus Google Ads / Meta einfügen]. Beschönige nichts.
```

## Prompt E: Nächster Monat

```
Neuer Monat für denselben Kunden. Erstelle einen neuen Social-Media-Plan (wie Prompt B) mit neuen Themen und Winkeln,
ohne die Vormonate zu wiederholen. Berücksichtige: [Feedback des Kunden / Saison / neue Aktion].
```
