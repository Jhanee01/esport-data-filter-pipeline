"""One pass of the pipeline: fetch offers, run every strategy, record and send new signals.

Each (strategy, offer) pair is signalled at most once: the database enforces it, so a
restart or an overlapping poll can't send the same tip twice.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import features as feat
from .battle_day import TZ, session_of, to_local
from .odds.base import OddsSource, Offer
from .sinks.telegram import TelegramSink, format_signal
from .store import insert_signal, mark_sent, now_utc, set_meta
from .strategies.base import Strategy

log = logging.getLogger(__name__)

MIN_LEAD = timedelta(minutes=1)  # don't signal a match that is about to start


@dataclass
class CycleReport:
    offers: int = 0
    evaluated: int = 0
    new_signals: list[int] = field(default_factory=list)
    send_errors: int = 0
    strategy_errors: dict[str, str] = field(default_factory=dict)


def _store_offers(conn: sqlite3.Connection, offers: list[Offer]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO offers(key, source, fetched_at, kickoff_utc, venue, format, player1,"
        " team1, player2, team2, market, line, pick, odds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                o.key,
                o.source,
                now_utc(),
                o.kickoff_utc,
                o.venue,
                o.format,
                o.player1,
                o.team1,
                o.player2,
                o.team2,
                o.market,
                o.line,
                o.pick,
                o.odds,
            )
            for o in offers
        ],
    )
    conn.commit()


def run_cycle(
    conn: sqlite3.Connection,
    source: OddsSource,
    strategies: list[Strategy],
    sink: TelegramSink | None,
    sessions: dict[str, tuple[str, str]],
    now: datetime | None = None,
) -> CycleReport:
    now = now or datetime.now(UTC)
    report = CycleReport()
    try:
        offers = source.fetch()
    except Exception as e:  # the source promises not to raise, but don't trust it
        log.error("odds source %s failed: %s", source.name, e)
        report.strategy_errors["<source>"] = str(e)
        return report
    report.offers = len(offers)
    _store_offers(conn, offers)
    if offers:
        set_meta(conn, "last_offers_at", now_utc())

    cache: dict[tuple, feat.Features] = {}
    for offer in offers:
        kickoff = datetime.fromisoformat(offer.kickoff_utc.replace("Z", "+00:00"))
        if kickoff - now < MIN_LEAD:
            continue
        local = to_local(offer.kickoff_utc)
        session = session_of(local.strftime("%H:%M"), sessions)
        for strategy in strategies:
            if not strategy.enabled or not strategy.wants(offer, session):
                continue
            key = (
                offer.player1,
                offer.player2,
                offer.kickoff_utc,
                offer.format,
                offer.line,
                offer.odds,
                strategy.h2h_window,
                strategy.form_window,
            )
            if key not in cache:
                cache[key] = feat.compute(
                    conn,
                    offer.player1,
                    offer.player2,
                    offer.kickoff_utc,
                    fmt=offer.format,
                    line=offer.line,
                    odds=offer.odds,
                    h2h_window=strategy.h2h_window,
                    form_window=strategy.form_window,
                )
            report.evaluated += 1
            try:
                decision = strategy.evaluate(offer, cache[key])
            except Exception as e:  # one broken strategy must not stop the rest
                report.strategy_errors[strategy.id] = f"{type(e).__name__}: {e}"
                continue
            if decision is None:
                continue
            signal_id = insert_signal(
                conn,
                strategy.id,
                offer.as_dict(),
                session,
                {"reason": decision.reason, **decision.details, "features": cache[key].as_dict()},
            )
            if signal_id is None:
                continue  # already signalled earlier
            report.new_signals.append(signal_id)
            # unrouted signals are only recorded locally: sent_at stays empty
            if sink is not None and sink.routing.chat_for(strategy.id, session):
                text = format_signal(
                    strategy.name,
                    offer.as_dict(),
                    decision.reason,
                    local.astimezone(TZ).strftime("%m-%d %H:%M"),
                )
                error = sink.send(strategy.id, session, text)
                mark_sent(conn, signal_id, error)
                report.send_errors += error is not None
    return report
