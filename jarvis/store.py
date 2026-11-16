"""SQLite-Speicher: Kandidaten, Firmen, Anrufe, Chats, Opt-outs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta

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
    status TEXT DEFAULT 'neu'
);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    city TEXT,
    phone TEXT,
    website TEXT,
    needs TEXT,
    source_url TEXT,
    status TEXT DEFAULT 'neu',
    notes TEXT DEFAULT '',
    found_on TEXT,
    UNIQUE(name, city)
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT,           -- kandidat | firma
    target_key TEXT,
    phone TEXT,
    call_sid TEXT,
    started TEXT,
    status TEXT DEFAULT 'geplant',
    transcript TEXT DEFAULT '[]',
    summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chats (
    phone TEXT PRIMARY KEY,
    messages TEXT DEFAULT '[]',
    updated TEXT
);
CREATE TABLE IF NOT EXISTS optout (
    phone TEXT PRIMARY KEY,
    added TEXT
);
"""

CANDIDATE_EXTRA_COLUMNS = {
    "consent_whatsapp": "INTEGER DEFAULT 0",
    "consent_call": "INTEGER DEFAULT 0",
    "notes": "TEXT DEFAULT ''",
    "last_contact": "TEXT",
}

COMPANY_EXTRA_COLUMNS = {
    "email": "TEXT",          # Ansprechperson HR (aus Telefonat oder manuell)
    "contact_name": "TEXT",
}

STATUSES = ("neu", "kontaktiert", "interessiert", "kein_interesse", "vermittelt")
COMPANY_STATUSES = ("neu", "angerufen", "interessiert", "kein_bedarf", "nicht_anrufen")

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, extra in (("candidates", CANDIDATE_EXTRA_COLUMNS), ("companies", COMPANY_EXTRA_COLUMNS)):
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in extra.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()
    return conn


def digits(phone: str | None) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


# --------------------------------------------------------------------------- Kandidaten
def candidate_key(c: ScoredCandidate) -> str:
    a = c.assessment
    ident = (a.phone or a.email or f"{a.full_name}|{c.source}").lower().replace(" ", "")
    return hashlib.sha256(ident.encode()).hexdigest()[:16]


def upsert(conn: sqlite3.Connection, c: ScoredCandidate) -> bool:
    """Speichert den Kandidaten. Gibt True zurück, wenn er neu ist."""
    key = candidate_key(c)
    with _lock:
        exists = conn.execute("SELECT 1 FROM candidates WHERE key=?", (key,)).fetchone()
        conn.execute(
            """INSERT INTO candidates (key, name, phone, category, tier, score, source, data,
                                       found_on, consent_whatsapp, consent_call)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET tier=excluded.tier, score=excluded.score,
                 data=excluded.data,
                 consent_whatsapp=MAX(consent_whatsapp, excluded.consent_whatsapp),
                 consent_call=MAX(consent_call, excluded.consent_call)""",
            (key, c.assessment.full_name, c.assessment.phone, c.assessment.category, c.tier,
             c.score, c.source, c.model_dump_json(), date.today().isoformat(),
             int(c.consent_whatsapp), int(c.consent_call)),
        )
        conn.commit()
    return exists is None


def get_candidate(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Volle ID oder eindeutiger Anfang (z.B. die ersten 6 Zeichen)."""
    key = (key or "").strip().lower()
    row = conn.execute("SELECT * FROM candidates WHERE key=?", (key,)).fetchone()
    if row or len(key) < 4:
        return row
    rows = conn.execute("SELECT * FROM candidates WHERE key LIKE ? LIMIT 2", (key + "%",)).fetchall()
    return rows[0] if len(rows) == 1 else None


def find_candidate_by_phone(conn: sqlite3.Connection, phone: str) -> sqlite3.Row | None:
    d = digits(phone)
    for row in conn.execute("SELECT * FROM candidates WHERE phone IS NOT NULL"):
        rd = digits(row["phone"])
        if rd and (rd[-9:] == d[-9:]):
            return row
    return None


def load(row: sqlite3.Row) -> ScoredCandidate:
    return ScoredCandidate.model_validate(json.loads(row["data"]))


def todays_shortlist(conn: sqlite3.Connection, limit: int) -> list[ScoredCandidate]:
    rows = conn.execute(
        """SELECT data FROM candidates
           WHERE status='neu' AND tier IN ('A','B') AND phone IS NOT NULL
           ORDER BY score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [ScoredCandidate.model_validate(json.loads(r[0])) for r in rows]


def set_status(conn: sqlite3.Connection, key: str, status: str, note: str = "") -> None:
    if status not in STATUSES:
        raise ValueError(f"Status muss einer von {STATUSES} sein")
    row = get_candidate(conn, key)
    if row is None:
        raise ValueError(f"Kandidat {key} nicht gefunden")
    key = row["key"]
    with _lock:
        conn.execute(
            "UPDATE candidates SET status=?, last_contact=?, notes=notes || ? WHERE key=?",
            (status, datetime.now().isoformat(timespec="minutes"),
             f"\n{date.today()}: {note}" if note else "", key),
        )
        conn.commit()


def list_all(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT key, name, category, tier, score, status, found_on FROM candidates ORDER BY score DESC"
    ).fetchall()


def callable_candidates(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """A/B-Kandidaten mit Anruf-Einwilligung, die noch nie angerufen wurden."""
    rows = conn.execute(
        """SELECT c.* FROM candidates c
           WHERE c.status='neu' AND c.tier IN ('A','B') AND c.consent_call=1 AND c.phone IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM calls k WHERE k.target_type='kandidat' AND k.target_key=c.key)
           ORDER BY c.score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [r for r in rows if not is_opted_out(conn, r["phone"])]


def stats_today(conn: sqlite3.Connection) -> dict:
    today = date.today().isoformat()
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    return {
        "neu_heute": q("SELECT COUNT(*) FROM candidates WHERE found_on=?", today),
        "vermittelbar_heute": q(
            "SELECT COUNT(*) FROM candidates WHERE found_on=? AND tier IN ('A','B')", today),
        "A_gesamt_offen": q("SELECT COUNT(*) FROM candidates WHERE tier='A' AND status='neu'"),
        "interessiert": q("SELECT COUNT(*) FROM candidates WHERE status='interessiert'"),
        "anrufe_heute": q("SELECT COUNT(*) FROM calls WHERE started LIKE ?", today + "%"),
        "firmen_offen": q("SELECT COUNT(*) FROM companies WHERE status='neu'"),
        "firmen_interessiert": q("SELECT COUNT(*) FROM companies WHERE status='interessiert'"),
    }


# --------------------------------------------------------------------------- Firmen
def add_company(conn: sqlite3.Connection, **f) -> bool:
    with _lock:
        cur = conn.execute(
            """INSERT OR IGNORE INTO companies (name, city, phone, website, needs, source_url, found_on)
               VALUES (?,?,?,?,?,?,?)""",
            (f.get("name"), f.get("city"), f.get("phone"), f.get("website"), f.get("needs"),
             f.get("source_url"), date.today().isoformat()),
        )
        conn.commit()
    return cur.rowcount > 0


def get_company(conn: sqlite3.Connection, cid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()


def list_companies(conn: sqlite3.Connection, status: str | None = None, limit: int = 50):
    if status:
        return conn.execute("SELECT * FROM companies WHERE status=? ORDER BY id DESC LIMIT ?",
                            (status, limit)).fetchall()
    return conn.execute("SELECT * FROM companies ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def set_company_status(conn: sqlite3.Connection, cid: int, status: str, note: str = "") -> None:
    if status not in COMPANY_STATUSES:
        raise ValueError(f"Status muss einer von {COMPANY_STATUSES} sein")
    with _lock:
        conn.execute("UPDATE companies SET status=?, notes=notes || ? WHERE id=?",
                     (status, f"\n{date.today()}: {note}" if note else "", cid))
        conn.commit()


def callable_companies(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM companies WHERE status='neu' AND phone IS NOT NULL AND phone != '' "
        "ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [r for r in rows if not is_opted_out(conn, r["phone"])]


# --------------------------------------------------------------------------- Anrufe
def create_call(conn: sqlite3.Connection, target_type: str, target_key: str, phone: str) -> int:
    with _lock:
        cur = conn.execute(
            "INSERT INTO calls (target_type, target_key, phone, started) VALUES (?,?,?,?)",
            (target_type, target_key, phone, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    return cur.lastrowid


def update_call(conn: sqlite3.Connection, call_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        conn.execute(f"UPDATE calls SET {cols} WHERE id=?", (*fields.values(), call_id))
        conn.commit()


def get_call(conn: sqlite3.Connection, call_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()


# --------------------------------------------------------------------------- Chats & Opt-out
def load_chat(conn: sqlite3.Connection, phone: str) -> tuple[list, str | None]:
    row = conn.execute("SELECT messages, updated FROM chats WHERE phone=?", (digits(phone),)).fetchone()
    if not row:
        return [], None
    return json.loads(row["messages"]), row["updated"]


def save_chat(conn: sqlite3.Connection, phone: str, messages: list) -> None:
    with _lock:
        conn.execute(
            "INSERT INTO chats (phone, messages, updated) VALUES (?,?,?) "
            "ON CONFLICT(phone) DO UPDATE SET messages=excluded.messages, updated=excluded.updated",
            (digits(phone), json.dumps(messages, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()


def add_optout(conn: sqlite3.Connection, phone: str) -> None:
    with _lock:
        conn.execute("INSERT OR IGNORE INTO optout (phone, added) VALUES (?,?)",
                     (digits(phone)[-9:], date.today().isoformat()))
        conn.commit()


def is_opted_out(conn: sqlite3.Connection, phone: str | None) -> bool:
    if not phone:
        return False
    return conn.execute("SELECT 1 FROM optout WHERE phone=?", (digits(phone)[-9:],)).fetchone() is not None


def grant_whatsapp_consent(conn: sqlite3.Connection, key: str) -> None:
    """Die Person hat uns selbst per WhatsApp geschrieben."""
    with _lock:
        conn.execute("UPDATE candidates SET consent_whatsapp=1 WHERE key=?", (key,))
        conn.commit()


# --------------------------------------------------------------------------- Zustand (Autopilot)
def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    conn.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT)")
    row = conn.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
    return row[0] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT)")
    with _lock:
        conn.execute("INSERT INTO state (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (key, value))
        conn.commit()


def set_company_contact(conn: sqlite3.Connection, cid: int, email: str | None, name: str | None) -> None:
    with _lock:
        conn.execute("UPDATE companies SET email=COALESCE(?, email), contact_name=COALESCE(?, contact_name) "
                     "WHERE id=?", (email, name, cid))
        conn.commit()


def followups_due(conn: sqlite3.Connection, days: int = 3) -> list[sqlite3.Row]:
    """Kontaktiert, aber seit X Tagen keine Rückmeldung → nachfassen."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="minutes")
    return conn.execute(
        "SELECT * FROM candidates WHERE status='kontaktiert' AND last_contact IS NOT NULL "
        "AND last_contact < ? ORDER BY score DESC LIMIT 20", (cutoff,)).fetchall()
