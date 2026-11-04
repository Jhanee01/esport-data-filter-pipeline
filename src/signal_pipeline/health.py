"""Health checks: is data flowing, are strategies loading, are signals going out?

Each check returns ok / warn / fail with a sentence (in Hungarian, like the UI) a human can act on. The dashboard
and the remote page show the same list.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .store import get_meta


@dataclass(frozen=True)
class Check:
    name: str
    level: str  # "ok" | "warn" | "fail"
    message: str


def _age(ts: str | None, now: datetime) -> timedelta | None:
    if not ts:
        return None
    return now - datetime.fromisoformat(ts.replace("Z", "+00:00"))


def run_checks(
    conn: sqlite3.Connection,
    strategy_count: int,
    strategy_errors: dict[str, str],
    now: datetime | None = None,
) -> list[Check]:
    now = now or datetime.now(UTC)
    out: list[Check] = []

    last_result = conn.execute("SELECT MAX(start_utc) FROM matches").fetchone()[0]
    age = _age(last_result, now)
    if age is None:
        out.append(
            Check(
                "results", "fail", "Még nincs eredmény: futtass gyűjtést vagy töltsd be a történeti adatot."
            )
        )
    elif age > timedelta(hours=3):
        out.append(
            Check("results", "warn", f"A legfrissebb eredmény {int(age.total_seconds() // 3600)} órás.")
        )
    else:
        out.append(Check("results", "ok", f"Legfrissebb eredmény: {int(age.total_seconds() // 60)} perce."))

    last_offers = get_meta(conn, "last_offers_at")
    age = _age(last_offers, now)
    if age is None or age > timedelta(minutes=10):
        out.append(Check("odds", "warn", "Az elmúlt 10 percben nem jött odds."))
    else:
        out.append(Check("odds", "ok", f"Utolsó odds: {int(age.total_seconds())} másodperce."))

    if strategy_errors:
        out.append(
            Check(
                "strategies",
                "fail",
                f"{len(strategy_errors)} stratégiafájl nem töltődött be: "
                + "; ".join(f"{k}: {v}" for k, v in list(strategy_errors.items())[:3]),
            )
        )
    elif strategy_count == 0:
        out.append(
            Check("strategies", "warn", "Nincs betöltött stratégia: hozz létre egyet a Stratégia laborban.")
        )
    else:
        out.append(Check("strategies", "ok", f"{strategy_count} stratégia betöltve."))

    unsent = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE send_error IS NOT NULL AND created_at > ?",
        ((now - timedelta(hours=24)).isoformat(),),
    ).fetchone()[0]
    out.append(
        Check(
            "telegram",
            "warn" if unsent else "ok",
            f"{unsent} jelzést nem sikerült elküldeni az elmúlt 24 órában."
            if unsent
            else "Az elmúlt 24 órában nem volt küldési hiba.",
        )
    )
    return out
