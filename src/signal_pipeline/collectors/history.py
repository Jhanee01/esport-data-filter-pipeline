"""Bulk history from esoccer-battle-mcp, so you don't have to scrape months of results.

Two ways in:
- `import_from_db(path)`  — copy from a local esoccer-battle-mcp database
                            (default: ~/.esoccer-battle-mcp/battle.db)
- `import_snapshot()`     — download the public data snapshot that esoccer-battle-mcp
                            publishes to its `data-latest` GitHub release (~12 MB)

Both copy the `matches` table as is; the columns are identical by design.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
import urllib.request
from pathlib import Path

from ..store import MATCH_COLUMNS

SNAPSHOT_URL = "https://github.com/Jhanee01/esoccer-battle-mcp/releases/download/data-latest/battle.db.gz"
DEFAULT_MCP_DB = Path.home() / ".esoccer-battle-mcp" / "battle.db"
MAX_DOWNLOAD = 300 * 1024 * 1024


def import_from_db(conn: sqlite3.Connection, source: Path = DEFAULT_MCP_DB) -> int:
    """Copy all finished matches from an esoccer-battle-mcp database. Returns rows copied."""
    if not source.exists():
        raise FileNotFoundError(f"no esoccer-battle-mcp database at {source}")
    cols = ", ".join(MATCH_COLUMNS)
    before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    conn.execute("ATTACH DATABASE ? AS mcp", (str(source),))
    try:
        conn.execute(f"INSERT OR REPLACE INTO main.matches({cols}) SELECT {cols} FROM mcp.matches")
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE mcp")
    return conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] - before


def import_snapshot(conn: sqlite3.Connection, url: str = SNAPSHOT_URL) -> int:
    """Download the esoccer-battle-mcp snapshot and import it."""
    with tempfile.TemporaryDirectory() as tmp:
        gz, db = Path(tmp) / "battle.db.gz", Path(tmp) / "battle.db"
        req = urllib.request.Request(url, headers={"User-Agent": "esport-data-filter-pipeline"})
        with urllib.request.urlopen(req, timeout=120) as r, open(gz, "wb") as f:
            size = 0
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("snapshot is larger than expected; aborting")
                f.write(chunk)
        with gzip.open(gz, "rb") as src, open(db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return import_from_db(conn, db)
