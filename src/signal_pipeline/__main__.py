"""Command line: `python -m signal_pipeline <command>`.

run              run the pipeline headless (collect, odds, strategies, Telegram, results)
ui               open the desktop dashboard
collect [DAYS]   fetch Battle results and fixtures for the last DAYS days (default 1)
import-history   copy history from esoccer-battle-mcp (local DB, or --snapshot to download)
backtest ID      backtest one strategy (see --help for the options)
status           health checks and per-strategy results
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from .config import load_settings


def _pipeline():
    from .service import Pipeline

    return Pipeline(load_settings())


def cmd_run(args) -> int:
    p = _pipeline()
    if args.remote:
        from .remote.server import serve_in_background

        serve_in_background(p)
    p.start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    p.close()
    return 0


def cmd_ui(args) -> int:
    from .ui.app import run_app

    return run_app(load_settings())


def cmd_collect(args) -> int:
    p = _pipeline()
    for s in p.collect(args.days):
        print(f"{s['day']}: {s['results']} results, {s['fixtures']} fixtures, {s['errors']} errors")
    p.close()
    return 0


def cmd_import(args) -> int:
    from .collectors import history
    from .store import connect

    conn = connect(load_settings().db_path)
    n = (
        history.import_snapshot(conn)
        if args.snapshot
        else history.import_from_db(conn, Path(args.db) if args.db else history.DEFAULT_MCP_DB)
    )
    print(f"imported {n} new matches")
    return 0


def cmd_backtest(args) -> int:
    from . import backtest

    p = _pipeline()
    strategy = next((s for s in p.loaded.strategies if s.id == args.id), None)
    if strategy is None:
        print(f"no strategy with id {args.id!r}; loaded: {[s.id for s in p.loaded.strategies]}")
        return 1
    r = backtest.run(
        p.conn,
        strategy,
        date_from=args.date_from,
        date_to=args.date_to,
        ou_lines=tuple(args.line),
        assumed_odds=args.odds,
        fmt=args.format,
    )
    hr = f"{r.hit_rate:.1%}" if r.hit_rate is not None else "—"
    be = f"{r.break_even_odds:.2f}" if r.break_even_odds else "—"
    print(
        f"{strategy.id}: {r.matches_scanned} matches, {r.signals} signals, {r.won}-{r.lost}-{r.push}"
        f" (W-L-P), hit rate {hr}, break-even odds {be}, units @ {r.assumed_odds}: {r.units:+.2f}"
    )
    for month, m in sorted(r.by_month.items()):
        print(f"  {month}: {m['signals']} signals, {m['won']}-{m['lost']}-{m['push']}")
    p.close()
    return 0


def cmd_status(args) -> int:
    from .resolver import summarise

    p = _pipeline()
    for c in p.health():
        print(f"[{c.level:4}] {c.name}: {c.message}")
    for s in summarise(p.conn):
        hr = f"{s.hit_rate:.1%}" if s.hit_rate is not None else "—"
        print(f"{s.strategy_id}: {s.signals} signals, {s.won}-{s.lost}-{s.push}, hit {hr}, {s.units:+.2f} u")
    p.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(
        prog="signal-pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--remote", action="store_true", help="also serve the phone remote page")
    r.set_defaults(func=cmd_run)
    sub.add_parser("ui").set_defaults(func=cmd_ui)
    c = sub.add_parser("collect")
    c.add_argument("days", nargs="?", type=int, default=1)
    c.set_defaults(func=cmd_collect)
    i = sub.add_parser("import-history")
    i.add_argument("--snapshot", action="store_true", help="download the public snapshot")
    i.add_argument("--db", help="path to an esoccer-battle-mcp battle.db")
    i.set_defaults(func=cmd_import)
    b = sub.add_parser("backtest")
    b.add_argument("id")
    b.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    b.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    b.add_argument("--line", type=float, action="append", default=None, help="O/U line(s), default 5.5")
    b.add_argument("--odds", type=float, default=1.9, help="assumed price, default 1.9")
    b.add_argument("--format", choices=["8min", "12min"])
    b.set_defaults(func=cmd_backtest)
    sub.add_parser("status").set_defaults(func=cmd_status)
    args = ap.parse_args(argv)
    if getattr(args, "line", "x") is None:
        args.line = [5.5]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
