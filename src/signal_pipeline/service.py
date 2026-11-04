"""The running pipeline: wires settings, storage, source, strategies and Telegram together,
and runs the loops in a background thread. The dashboard, the CLI and the remote page all
talk to one `Pipeline` instance.
"""

from __future__ import annotations

import collections
import logging
import threading
import time

from . import engine, health, resolver
from .battle_day import days_back, today_battle_day
from .collectors import battle_api
from .config import Settings
from .odds.base import OddsSource, load_source
from .sinks.telegram import Routing, TelegramSink
from .store import connect
from .strategies.loader import LoadResult, load_all

log = logging.getLogger("signal_pipeline")

COLLECT_EVERY_S = 10 * 60
RESOLVE_EVERY_S = 5 * 60


class _RingHandler(logging.Handler):
    """Keeps the last N log lines in memory for the dashboard and the remote page."""

    def __init__(self, size: int = 500):
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


class Pipeline:
    def __init__(self, settings: Settings, source: OddsSource | None = None):
        self.settings = settings
        self.conn = connect(settings.db_path)
        self.lock = threading.RLock()  # one sqlite connection, many threads
        self.ring = _RingHandler()
        logging.getLogger().addHandler(self.ring)
        self.source = source or load_source(
            settings.odds_source,
            **({"conn": self.conn} if settings.odds_source.endswith(":DemoOddsSource") else {}),
        )
        self.loaded = LoadResult()
        self.reload_strategies()
        self.sink = TelegramSink(settings.telegram_token, Routing.load(settings.routing_path))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_cycle: engine.CycleReport | None = None

    # -- actions ---------------------------------------------------------------------------

    def reload_strategies(self) -> LoadResult:
        with self.lock:
            self.loaded = load_all(self.settings.lab_dir, self.settings.strategies_dir)
        for name, err in self.loaded.errors.items():
            log.error("strategy load error %s: %s", name, err)
        log.info("strategies loaded: %s", ", ".join(s.id for s in self.loaded.strategies) or "none")
        return self.loaded

    def reload_routing(self) -> None:
        self.sink.routing = Routing.load(self.settings.routing_path)

    def collect(self, days: int = 1) -> list[dict]:
        out = []
        for day in days_back(today_battle_day(), days):
            with self.lock:
                stats = battle_api.collect_day(self.conn, day, self.settings.sessions)
            log.info(
                "collected %s: %d results, %d fixtures, %d errors",
                day,
                stats["results"],
                stats["fixtures"],
                stats["errors"],
            )
            out.append(stats)
        return out

    def cycle(self) -> engine.CycleReport:
        with self.lock:
            report = engine.run_cycle(
                self.conn, self.source, self.loaded.strategies, self.sink, self.settings.sessions
            )
        self.last_cycle = report
        if report.new_signals:
            log.info("new signals: %s", report.new_signals)
        for sid, err in report.strategy_errors.items():
            log.error("strategy %s failed: %s", sid, err)
        return report

    def resolve(self) -> dict[str, int]:
        with self.lock:
            counts = resolver.resolve_pending(self.conn)
        if any(v for k, v in counts.items() if k != "waiting"):
            log.info("resolved: %s", counts)
        return counts

    def health(self) -> list[health.Check]:
        with self.lock:
            return health.run_checks(self.conn, len(self.loaded.strategies), self.loaded.errors)

    # -- background loop -------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()
        log.info("pipeline started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        log.info("pipeline stopped")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _safe(self, action, name: str) -> None:
        try:
            action()
        except Exception:  # keep the loop alive; the log shows what broke
            log.exception("%s failed", name)

    def _run(self) -> None:
        next_collect = next_resolve = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_collect:
                self._safe(self.collect, "collect")
                next_collect = now + COLLECT_EVERY_S
            if now >= next_resolve:
                self._safe(self.resolve, "resolve")
                next_resolve = now + RESOLVE_EVERY_S
            self._safe(self.cycle, "cycle")
            self._stop.wait(self.settings.poll_seconds)

    def close(self) -> None:
        self.stop()
        self.source.close()
        logging.getLogger().removeHandler(self.ring)
        self.conn.close()
