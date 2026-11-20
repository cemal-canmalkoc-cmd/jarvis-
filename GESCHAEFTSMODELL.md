# Geschäftsmodell: Erfolgsbasierte Vermittlung von Pflege- & Medizinpersonal

## Ehrliche Vorbemerkung
- **Keine Garantie.** 10–20.000 €/Monat sind erreichbar, aber nicht sicher. Realistisch: Monate 1–3 meist **0 €**, erste Einnahmen nach 2–6 Monaten.
- **Nicht 100 % passiv.** Die Technik (Jobseiten, SEO, Formulare, tägliche Aktualisierung) läuft automatisch. Telefonate mit Kandidaten und Verträge mit Arbeitgebern macht ein Mensch: **ca. 5–10 Std./Woche** am Anfang.
- **Fast 0 € Kosten.** Hosting (GitHub Pages), Automatisierung (GitHub Actions) und Formular (Formspree/Tally, Gratis-Tarif) sind kostenlos. Unvermeidbar: **Gewerbeanmeldung (ca. 15–65 €, einmalig)**. Optional: eigene Domain (~1 €/Monat).

## Warum das funktionieren kann
- In Deutschland fehlen Zehntausende Pflegekräfte. Kliniken und Heime zahlen Vermittlern **etwa 15–25 % des Jahresbruttos** oder Pauschalen von **4.000–9.000 €** pro Einstellung.
- Für Kandidaten ist es **kostenlos**, deshalb bewerben sie sich leicht.
- Du zahlst nichts im Voraus. Geld fließt nur bei Erfolg, dein Risiko ist also nur deine Zeit.

## So läuft es
```
[GitHub Actions, täglich]  →  holt Pflege-Stellen (BA-Jobsuche-API)
            ↓
[Website, automatisch]     →  Seiten pro Stadt (Google findet sie) + "Über uns bewerben"
            ↓
[Kandidat füllt Formular]  →  landet in deinem Postfach (Formspree/Tally)
            ↓
[DU: 15-Min.-Telefonat]    →  Qualifikation prüfen, Einwilligung zur Weitergabe holen
            ↓
[DU: Arbeitgeber anrufen/mailen] → anonymes Profil + Provisionsvereinbarung (Vorlage unten)
            ↓
[Einstellung]              →  Rechnung an Arbeitgeber
```

## Rechnung
| Annahme | Wert |
|---|---|
| Honorar pro Vermittlung | 5.000–8.000 € |
| Benötigte Vermittlungen für 10–20 k€/Monat | **2–3 pro Monat** |
| Übliche Quote Bewerbung → Einstellung | ca. 3–5 % |
| Benötigte qualifizierte Bewerbungen/Monat | **ca. 50–80** |
| Benötigte Besucher/Monat (bei ~2 % Formular-Quote) | **ca. 3.000–4.000** |

Diese Besucherzahlen über Google aufzubauen dauert erfahrungsgemäß **3–9 Monate**. Schneller geht es mit kostenlosen Kanälen: Facebook-Gruppen für Pflegekräfte, TikTok/Instagram-Reels („Was verdient eine Pflegekraft in der Schweiz?“), Kleinanzeigen-Jobrubrik.

## Rechtliches (vor dem Start klären!)
1. **Deutschland:** Private Arbeitsvermittlung braucht **keine Erlaubnis**, nur eine **Gewerbeanmeldung**. Das Honorar zahlt der **Arbeitgeber**. Von Kandidaten nimmst du nichts.
   **Keine Arbeitnehmerüberlassung** (Leiharbeit) betreiben, dafür bräuchtest du eine Erlaubnis nach AÜG.
2. **Schweiz:** Personalvermittlung in die Schweiz braucht eine **Bewilligung (AVG)** und in der Regel einen **Sitz/Handelsregistereintrag in der Schweiz**. Ohne diese Bewilligung **nicht selbst vermitteln**. Möglicher Weg: Kandidaten an eine lizenzierte Schweizer Agentur weitergeben und dafür einen Anteil bekommen. Vorher von einer Fachperson prüfen lassen.
3. **DSGVO:** Bewerberdaten sind sensibel. Nötig sind Einwilligung (Checkbox ist eingebaut), eine Datenschutzerklärung (Entwurf liegt in `static/datenschutz.html`) und ein AV-Vertrag mit dem Formulardienst. Profile nur **mit Zustimmung im Einzelfall** an Arbeitgeber geben.
4. **Impressum** ausfüllen (`static/impressum.html`).
5. **Stellendaten der BA:** Die Seite verlinkt auf die Originalanzeigen und nennt die Quelle. Die Nutzungsbedingungen der BA solltest du selbst prüfen. Arbeitgeber zahlen nur, wenn **vor** der Vorstellung eines Kandidaten eine **schriftliche Provisionsvereinbarung** besteht.
6. Steuern: Kleinunternehmerregelung prüfen (bis 25.000 € Vorjahresumsatz). Bei 10 k€/Monat fällt Umsatzsteuer an, also mit Steuerberater sprechen.

## Dein Wochenplan
Der [digitale Mitarbeiter](MITARBEITER.md) übernimmt Postfach, Zustimmungen, Konditionen, Profilversand und Vorstellungen. Dir bleiben **ca. 2–4 Std./Woche**: Anrufliste abtelefonieren, offene Fragen beantworten, Rechnungen schreiben.

Ohne Mitarbeiter (ca. 5–10 Std.):
- **Mo:** Neue Bewerbungen sichten und Kandidaten anrufen (je 15 Min.)
- **Di/Mi:** Für jeden guten Kandidaten 3–5 passende Arbeitgeber aus den Jobseiten kontaktieren (Vorlage unten)
- **Do:** 2–3 Social-Media-Posts / Gruppenbeiträge
- **Fr:** Interviews koordinieren, Rechnungen schreiben

## Vorlage: E-Mail an Arbeitgeber
> Betreff: Examinierte Pflegefachkraft für Ihre Stelle „[Titel]“, verfügbar ab [Datum]
>
> Guten Tag [Name],
> zu Ihrer Ausschreibung „[Titel]“ (Ref. [refnr]) habe ich eine passende Kandidatin:
> – [Qualifikation], [X] Jahre Erfahrung, [Fachbereich]
> – verfügbar ab [Datum], Gehaltsvorstellung [X] € brutto/Jahr, wohnhaft im Umkreis von [Ort]
>
> Ich arbeite erfolgsbasiert: Sie zahlen nur bei Einstellung ([X] % des Jahresbruttos bzw. [X] € pauschal, mit 3 Monaten Nachbesetzungsgarantie).
> Wenn Sie die Vereinbarung bestätigen, sende ich Ihnen das vollständige Profil.
>
> Viele Grüße, [Name], [Firma], [Telefon]

## Start-Checkliste
- [ ] Gewerbe anmelden („Private Arbeitsvermittlung“)
- [ ] Impressum und Datenschutz ausfüllen (`static/`)
- [ ] Kostenloses Formular anlegen (Formspree oder Tally), URL in `config.json` → `formular_endpoint`
- [ ] `kontakt_email` und `firmenname` in `config.json` setzen
- [ ] GitHub: Settings → Pages → Source: **GitHub Actions**; Workflow startet täglich automatisch
- [ ] Seite in der Google Search Console anmelden und `sitemap.xml` einreichen (kostenlos)
- [ ] Provisionsvereinbarung als Vorlage erstellen (von einem Anwalt prüfen lassen, ggf. über die IHK)
- [ ] Erste 20 Posts in Pflege-Facebook-Gruppen / TikTok
