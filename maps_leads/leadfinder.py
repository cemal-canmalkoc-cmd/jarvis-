#!/usr/bin/env python3
"""Google-Maps-Leadfinder: findet lokale Betriebe mit schwacher Online-Praesenz.

Nutzt die offizielle Google Places API (New) – kein Scraping.
Beispiel:
    export GOOGLE_MAPS_API_KEY=...
    python leadfinder.py --branche "Friseur" --stadt "Köln" --stadt "Bonn"
    python leadfinder.py --demo          # ohne API-Key testen
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path

API_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.websiteUri", "places.nationalPhoneNumber", "places.rating",
    "places.userRatingCount", "places.googleMapsUri", "places.businessStatus",
    "nextPageToken",
])


@dataclass
class Lead:
    place_id: str
    name: str
    adresse: str
    telefon: str
    website: str
    bewertung: float
    anzahl_bewertungen: int
    maps_link: str
    branche: str
    stadt: str
    score: int = 0
    probleme: list[str] = field(default_factory=list)
    angebot: str = ""


def score_lead(lead: Lead) -> Lead:
    """Je hoeher der Score, desto groesser der Bedarf -> desto leichter der Verkauf."""
    score, probleme = 0, []
    if not lead.website:
        score += 50
        probleme.append("keine Website")
    elif any(h in lead.website for h in ("facebook.com", "instagram.com", "business.site", "jimdo", "wix")):
        score += 30
        probleme.append("nur Social-Media-/Baukasten-Seite")
    if lead.anzahl_bewertungen < 10:
        score += 25
        probleme.append(f"nur {lead.anzahl_bewertungen} Bewertungen")
    elif lead.anzahl_bewertungen < 30:
        score += 10
        probleme.append(f"wenige Bewertungen ({lead.anzahl_bewertungen})")
    if 0 < lead.bewertung < 4.0:
        score += 15
        probleme.append(f"Bewertung {lead.bewertung:.1f} unter 4,0")
    if not lead.telefon:
        score -= 20  # schwer erreichbar
    lead.score, lead.probleme = score, probleme
    lead.angebot = (
        "Website + Google-Profil-Paket (990 € + 49 €/Monat)" if not lead.website
        else "Google-Profil- & Bewertungs-Paket (390 € + 49 €/Monat)"
    )
    return lead


def _post(body: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": api_key,
                 "X-Goog-FieldMask": FIELD_MASK},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def search(branche: str, stadt: str, api_key: str, max_seiten: int = 3) -> list[Lead]:
    leads, token = [], None
    for _ in range(max_seiten):  # max. 60 Treffer pro Suche
        body = {"textQuery": f"{branche} in {stadt}", "languageCode": "de", "pageSize": 20}
        if token:
            body["pageToken"] = token
        data = _post(body, api_key)
        for p in data.get("places", []):
            if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                continue
            leads.append(Lead(
                place_id=p["id"], name=p.get("displayName", {}).get("text", ""),
                adresse=p.get("formattedAddress", ""), telefon=p.get("nationalPhoneNumber", ""),
                website=p.get("websiteUri", ""), bewertung=float(p.get("rating", 0) or 0),
                anzahl_bewertungen=int(p.get("userRatingCount", 0) or 0),
                maps_link=p.get("googleMapsUri", ""), branche=branche, stadt=stadt,
            ))
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(2)
    return leads


def demo_leads() -> list[Lead]:
    raw = [
        ("1", "Salon Bella", "", "0221 123456", 4.6, 7),
        ("2", "Haarwerk Müller", "https://facebook.com/haarwerk", "0221 654321", 3.8, 22),
        ("3", "Barber King", "https://barberking.de", "0221 111111", 4.8, 340),
        ("4", "Frisör Yilmaz", "", "", 4.2, 3),
    ]
    return [Lead(i, n, "Musterstr. 1, Köln", t, w, r, c, f"https://maps.google.com/?cid={i}",
                 "Friseur", "Köln") for i, n, w, t, r, c in raw]


def export(leads: list[Lead], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, md_path = out_dir / "leads.csv", out_dir / "anschreiben.md"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Score", "Name", "Telefon", "Website", "Bewertung", "Anzahl", "Probleme",
                    "Angebot", "Adresse", "Maps", "Status", "Notiz"])
        for l in leads:
            w.writerow([l.score, l.name, l.telefon, l.website, l.bewertung, l.anzahl_bewertungen,
                        ", ".join(l.probleme), l.angebot, l.adresse, l.maps_link, "offen", ""])
    tpl = (Path(__file__).parent / "vorlagen" / "telefonskript.md").read_text(encoding="utf-8")
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Personalisierte Gesprächsleitfäden\n\n")
        for l in leads:
            f.write(f"## {l.name} (Score {l.score}) – {l.telefon or 'keine Nummer'}\n\n")
            f.write(tpl.format(name=l.name, branche=l.branche, stadt=l.stadt,
                               problem=", ".join(l.probleme) or "Online-Auftritt ausbaufähig",
                               angebot=l.angebot, bewertungen=l.anzahl_bewertungen))
            f.write("\n---\n\n")
    return csv_path, md_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branche", action="append", default=[], help="z. B. Friseur, Handwerker, Zahnarzt")
    ap.add_argument("--stadt", action="append", default=[], help="mehrfach angebbar")
    ap.add_argument("--min-score", type=int, default=40)
    ap.add_argument("--out", type=Path, default=Path("ergebnisse"))
    ap.add_argument("--demo", action="store_true", help="Beispieldaten statt API")
    a = ap.parse_args(argv)

    if a.demo:
        leads = demo_leads()
    else:
        key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if not key or not a.branche or not a.stadt:
            ap.error("GOOGLE_MAPS_API_KEY setzen und --branche/--stadt angeben (oder --demo)")
        leads = [l for b in a.branche for s in a.stadt for l in search(b, s, key)]

    seen, uniq = set(), []
    for l in leads:
        if l.place_id not in seen:
            seen.add(l.place_id)
            uniq.append(score_lead(l))
    top = sorted((l for l in uniq if l.score >= a.min_score), key=lambda l: -l.score)
    csv_path, md_path = export(top, a.out)
    print(f"{len(uniq)} Betriebe geprüft, {len(top)} heiße Leads (Score ≥ {a.min_score})")
    print(f"→ {csv_path}\n→ {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
