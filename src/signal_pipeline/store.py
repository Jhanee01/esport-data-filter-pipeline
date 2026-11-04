"""SQLite storage for results, odds offers and signals.

The `matches` table uses the same columns as esoccer-battle-mcp, so history can be copied
straight from its database or its public snapshot (see `collectors/history.py`).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    tournament_id INTEGER,
    battle_day TEXT, start_utc TEXT, local_date TEXT, local_time TEXT,
    venue TEXT, format TEXT, turnus INTEGER, session TEXT,
    player1 TEXT, team1 TEXT, player2 TEXT, team2 TEXT,
    score1 INTEGER, score2 INTEGER, corners1 INTEGER, corners2 INTEGER
);
CREATE INDEX IF NOT EXISTS ix_matches_start ON matches(start_utc);
CREATE INDEX IF NOT EXISTS ix_matches_p1 ON matches(player1 COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_matches_p2 ON matches(player2 COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS fixtures (
    id INTEGER PRIMARY KEY,
    start_utc TEXT, local_date TEXT, local_time TEXT, battle_day TEXT,
    venue TEXT, format TEXT, session TEXT,
    player1 TEXT, team1 TEXT, player2 TEXT, team2 TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    key TEXT PRIMARY KEY,
    source TEXT, fetched_at TEXT, kickoff_utc TEXT, venue TEXT, format TEXT,
    player1 TEXT, team1 TEXT, player2 TEXT, team2 TEXT,
    market TEXT, line REAL, pick TEXT, odds REAL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    offer_key TEXT NOT NULL,
    created_at TEXT, sent_at TEXT, send_error TEXT,
    kickoff_utc TEXT, venue TEXT, format TEXT, session TEXT,
    player1 TEXT, team1 TEXT, player2 TEXT, team2 TEXT,
    market TEXT, line REAL, pick TEXT, odds REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    score1 INTEGER, score2 INTEGER, resolved_at TEXT,
    details TEXT,
    UNIQUE(strategy_id, offer_key)
);
CREATE INDEX IF NOT EXISTS ix_signals_status ON signals(status);

CREATE TABLE IF NOT EXISTS tournaments_done (id INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

MATCH_COLUMNS = (
    "id",
    "tournament_id",
    "battle_day",
    "start_utc",
    "local_date",
    "local_time",
    "venue",
    "format",
    "turnus",
    "session",
    "player1",
    "team1",
    "player2",
    "team2",
    "score1",
    "score2",
    "corners1",
    "corners2",
)


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def upsert_matches(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ", ".join(MATCH_COLUMNS)
    marks = ", ".join("?" for _ in MATCH_COLUMNS)
    conn.executemany(
        f"INSERT OR REPLACE INTO matches({cols}) VALUES ({marks})",
        [tuple(r.get(c) for c in MATCH_COLUMNS) for r in rows],
    )
    conn.commit()
    return len(rows)


@dataclass(frozen=True)
class SignalRow:
    id: int
    strategy_id: str
    status: str
    kickoff_utc: str
    player1: str
    player2: str
    market: str
    line: float | None
    pick: str
    odds: float | None


def insert_signal(
    conn: sqlite3.Connection, strategy_id: str, offer: dict, session: str | None, details: dict
) -> int | None:
    """Store a new signal. Returns its id, or None if this strategy already signalled this offer."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO signals(strategy_id, offer_key, created_at, kickoff_utc, venue, format,"
        " session, player1, team1, player2, team2, market, line, pick, odds, details)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            strategy_id,
            offer["key"],
            now_utc(),
            offer["kickoff_utc"],
            offer.get("venue"),
            offer.get("format"),
            session,
            offer["player1"],
            offer.get("team1"),
            offer["player2"],
            offer.get("team2"),
            offer["market"],
            offer.get("line"),
            offer["pick"],
            offer.get("odds"),
            json.dumps(details, ensure_ascii=False),
        ),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def mark_sent(conn: sqlite3.Connection, signal_id: int, error: str | None = None) -> None:
    conn.execute(
        "UPDATE signals SET sent_at = ?, send_error = ? WHERE id = ?",
        (None if error else now_utc(), error, signal_id),
    )
    conn.commit()
