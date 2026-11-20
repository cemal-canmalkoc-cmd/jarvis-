# jarvis-
Automatisierte Personalfindung in der Schweiz, medizinischen Bereich sowie Personal in Deutschland und Arbeitgeber automatisiert

**→ Geschäftsmodell, Zahlen, Rechtliches & Checkliste: [GESCHAEFTSMODELL.md](GESCHAEFTSMODELL.md)**

## Was hier automatisch läuft
- `scripts/build.py` holt täglich Pflege-/Medizin-Stellen aus der BA-Jobsuche-API und baut eine statische Job-Website (Startseite, Seite pro Stadt, Bewerbung, Arbeitgeber, Schweiz, Sitemap).
- `.github/workflows/website.yml` führt das täglich aus und veröffentlicht kostenlos auf GitHub Pages.

## Einrichten
1. `config.json` anpassen (Firmenname, E-Mail, Formular-URL, Städte, Suchbegriffe).
2. `static/impressum.html` und `static/datenschutz.html` ausfüllen.
3. Auf GitHub: Settings → Pages → Source: „GitHub Actions“. Den Workflow nach `main` mergen.

Lokal testen: `python3 scripts/build.py` (ohne Internet: `--offline`), dann `_site/index.html` öffnen.
