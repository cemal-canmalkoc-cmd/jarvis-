"""SQLite-Speicher: Dubletten vermeiden und Kontaktstatus verfolgen."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date

from .config import DB_PATH
from .models import ScoredCandidate

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    key TEXT PRIMARY KEY,
    name TEXT,
    phone TEXT,
    category TEXT,
    tier TEXT,
    score INTEGER,
    source TEXT,
    data TEXT,
    found_on TEXT,
    status TEXT DEFAULT 'neu'   -- neu | kontaktiert | interessiert | kein_interesse | vermittelt
);
"""

STATUSES = ("neu", "kontaktiert", "interessiert", "kein_interesse", "vermittelt")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def candidate_key(c: ScoredCandidate) -> str:
    a = c.assessment
    ident = (a.phone or a.email or f"{a.full_name}|{c.source}").lower().replace(" ", "")
    return hashlib.sha256(ident.encode()).hexdigest()[:16]


def upsert(conn: sqlite3.Connection, c: ScoredCandidate) -> bool:
    """Speichert den Kandidaten. Gibt True zurück, wenn er neu ist."""
    key = candidate_key(c)
    exists = conn.execute("SELECT 1 FROM candidates WHERE key=?", (key,)).fetchone()
    conn.execute(
        """INSERT INTO candidates (key, name, phone, category, tier, score, source, data, found_on)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET tier=excluded.tier, score=excluded.score, data=excluded.data""",
        (key, c.assessment.full_name, c.assessment.phone, c.assessment.category, c.tier,
         c.score, c.source, c.model_dump_json(), date.today().isoformat()),
    )
    conn.commit()
    return exists is None


def todays_shortlist(conn: sqlite3.Connection, limit: int) -> list[ScoredCandidate]:
    rows = conn.execute(
        """SELECT data FROM candidates
           WHERE status='neu' AND tier IN ('A','B') AND phone IS NOT NULL
           ORDER BY score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [ScoredCandidate.model_validate(json.loads(r[0])) for r in rows]


def set_status(conn: sqlite3.Connection, key: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"Status muss einer von {STATUSES} sein")
    conn.execute("UPDATE candidates SET status=? WHERE key=?", (status, key))
    conn.commit()


def list_all(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT key, name, category, tier, score, status, found_on FROM candidates ORDER BY score DESC"
    ).fetchall()
