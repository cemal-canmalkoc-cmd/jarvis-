"""Automatische Stellen aus echtem Bedarf: Arbeitgeber, die Jarvis mit offenen Stellen gefunden hat,
werden je Bereich und Region zu einer anonymen Sammelstelle zusammengefasst.

Ehrlich bleiben: kein Firmenname, kein erfundenes Gehalt, kein kopierter Anzeigentext,
nicht an Google Jobs gemeldet (nur manuell eingetragene Einzelstellen). Stellen ohne aktuellen
Bedarf (keine passende Firma mehr gefunden in den letzten 45 Tagen) gehen automatisch offline.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import store

TITLES = {"lkw": "LKW-Fahrer CE / C (m/w/d)", "pflege": "Pflegefachkraft (m/w/d) – Schweiz",
          "arzt": "Ärztin / Arzt (m/w/d) – Schweiz"}
ARZT = re.compile(r"arzt|ärzt|mediziner|facharzt|oberarzt|assistenzarzt", re.I)
LKW = re.compile(r"lkw|fahrer|kraftfahrer|ce\b|spedition|logistik", re.I)


def bereich_of(firm) -> str | None:
    text = f"{firm['needs'] or ''} {firm['branche'] or ''}"
    if (firm["branche"] or "") == "lkw" or LKW.search(text):
        return "lkw"
    if ARZT.search(text):
        return "arzt"
    if text.strip():
        return "pflege"
    return None


def _region(city: str | None) -> str:
    c = (city or "").strip()
    c = re.sub(r"^\d{4,5}\s*", "", c)          # PLZ vorne weg
    return c.split(",")[0].strip() or ""


def describe(bereich: str, region: str, n: int, needs: list[str]) -> str:
    kinds = sorted({re.sub(r"\s+", " ", x).strip()[:60] for x in needs if x and len(x) < 120})[:5]
    who = {"lkw": "Speditionen und Logistikunternehmen", "pflege": "Spitäler, Kliniken und Heime",
           "arzt": "Kliniken"}[bereich]
    lines = [f"Aktuell suchen {n} {who} im Raum {region} Verstärkung." if n > 1 else
             f"Aktuell sucht ein Unternehmen ({who.split(' und ')[0].rstrip('n')}) im Raum {region} Verstärkung.",
             "", "Gesucht werden u. a.:"] + [f"• {k}" for k in kinds or [TITLES[bereich]]]
    if bereich == "lkw":
        lines += ["", "Das bringst du mit:", "• Führerschein C oder CE, Fahrerkarte, Modul 95 (ADR von Vorteil)",
                  "", "Unser Service:", "• Wir stellen dich passenden Speditionen vor – für dich kostenlos",
                  "• Konditionen besprechen wir je nach Arbeitgeber direkt mit dir"]
    else:
        lines += ["", "Das bringen Sie mit:", "• Diplom/Examen und Deutsch B2 (Ärzte: MEBEKO von Vorteil)",
                  "", "Unser Service:", "• Wir begleiten Sie bis zur Anstellung, inkl. Anerkennung – kostenlos",
                  "• Konditionen je nach Arbeitgeber, wir besprechen alles persönlich"]
    return "\n".join(lines)


def sync(days: int = 45) -> dict:
    """Automatische Sammelstellen anlegen/aktualisieren/abschalten."""
    conn = store.connect()
    since = (date.today() - timedelta(days=days)).isoformat()
    groups: dict[tuple[str, str], list] = {}
    for f in conn.execute("SELECT * FROM companies WHERE status NOT IN ('kein_bedarf','nicht_anrufen') "
                          "AND (found_on IS NULL OR found_on >= ?) AND needs IS NOT NULL AND needs != ''",
                          (since,)).fetchall():
        b, region = bereich_of(f), _region(f["city"])
        if b and region:
            groups.setdefault((b, region), []).append(f)
    existing = {r["auto_key"]: dict(r) for r in conn.execute("SELECT * FROM jobs WHERE auto_key IS NOT NULL")}
    made = updated = off = 0
    keys = set()
    for (b, region), firms in groups.items():
        key = f"{b}|{region.lower()}"
        keys.add(key)
        title = f"{TITLES[b]} – Raum {region}" if b == "lkw" else f"{TITLES[b]} ({region})"
        text = describe(b, region, len(firms), [f["needs"] for f in firms])
        if key in existing:
            with store._lock:
                conn.execute("UPDATE jobs SET title=?, beschreibung=?, active=1 WHERE auto_key=?", (title, text, key))
                conn.commit()
            updated += 1
        else:
            jid = store.add_job(conn, title, b, region, text, "")
            with store._lock:
                conn.execute("UPDATE jobs SET auto_key=? WHERE id=?", (key, jid))
                conn.commit()
            made += 1
    for key, j in existing.items():
        if key not in keys and j["active"]:
            store.set_job_active(conn, j["id"], False)
            off += 1
    return {"neu": made, "aktualisiert": updated, "offline": off}
