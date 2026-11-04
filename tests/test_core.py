import json
from datetime import timedelta

import pytest
from conftest import BASE, iso, match

from signal_pipeline import backtest, features
from signal_pipeline.battle_day import battle_day, session_of
from signal_pipeline.config import DEFAULT_SESSIONS
from signal_pipeline.engine import run_cycle
from signal_pipeline.markets import profit, settle
from signal_pipeline.odds.base import OddsSource, Offer, load_source
from signal_pipeline.odds.demo import DemoOddsSource
from signal_pipeline.resolver import resolve_pending, summarise
from signal_pipeline.sinks.telegram import Routing, TelegramSink
from signal_pipeline.store import upsert_matches
from signal_pipeline.strategies import RuleError, RuleStrategy, load_all, save_rule

KICKOFF = BASE + timedelta(days=1)


def rule(**over) -> dict:
    spec = {
        "id": "test-rule",
        "name": "Test",
        "market": "ou",
        "pick": "over",
        "conditions": [
            {"feature": "h2h_n", "op": ">=", "value": 5},
            {"feature": "h2h_over_rate", "op": ">=", "value": 0.5},
        ],
    }
    spec.update(over)
    return spec


class FixedSource(OddsSource):
    name = "fixed"

    def __init__(self, offers):
        self.offers = offers

    def fetch(self):
        return list(self.offers)


def offer(**over) -> Offer:
    base = dict(
        source="fixed",
        kickoff_utc=iso(KICKOFF),
        player1="Ann",
        player2="Bob",
        market="ou",
        pick="over",
        line=5.5,
        odds=1.9,
        format="8min",
        venue="Wembley",
    )
    base.update(over)
    return Offer(**base)


# --- battle day & sessions ---------------------------------------------------------------


def test_battle_day_starts_at_six():
    from signal_pipeline.battle_day import TZ, datetime

    assert battle_day(datetime(2026, 3, 2, 5, 59, tzinfo=TZ)) == "2026-03-01"
    assert battle_day(datetime(2026, 3, 2, 6, 0, tzinfo=TZ)) == "2026-03-02"
    assert battle_day(datetime(2026, 3, 2, 1, 0, tzinfo=TZ), "Some League 2026-02-28") == "2026-02-28"


def test_session_windows_wrap_midnight():
    assert session_of("06:00", DEFAULT_SESSIONS) == "day"
    assert session_of("21:59", DEFAULT_SESSIONS) == "afternoon"
    assert session_of("23:30", DEFAULT_SESSIONS) == "night"
    assert session_of("03:00", DEFAULT_SESSIONS) == "night"


# --- markets -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market,pick,line,s1,s2,expected",
    [
        ("ou", "over", 5.5, 3, 3, "won"),
        ("ou", "under", 5.5, 3, 3, "lost"),
        ("ou", "over", 6.0, 3, 3, "push"),
        ("1x2", "draw", None, 2, 2, "won"),
        ("1x2", "away", None, 1, 2, "won"),
        ("btts", "yes", None, 0, 4, "lost"),
    ],
)
def test_settle(market, pick, line, s1, s2, expected):
    assert settle(market, pick, line, s1, s2) == expected


def test_profit():
    assert profit("won", 1.9) == pytest.approx(0.9)
    assert profit("lost", 1.9) == -1
    assert profit("push", 1.9) == 0


# --- features never see the future --------------------------------------------------------


def test_features_use_only_past_matches(seeded):
    f = features.compute(seeded, "Ann", "Bob", iso(KICKOFF), line=5.5, odds=2.0)
    assert f.h2h_n == 10  # the match 30 days later is excluded
    assert f.h2h_over_rate == pytest.approx(0.6)
    assert f.h2h_p1_win_rate == pytest.approx(0.6)  # reversed rows are mirrored
    assert f.implied_prob == pytest.approx(0.5)


def test_features_respect_cutoff(seeded):
    f = features.compute(seeded, "Ann", "Bob", iso(BASE + timedelta(minutes=25)), line=5.5)
    assert f.h2h_n == 3


# --- rules -------------------------------------------------------------------------------


def test_rule_validation_messages():
    with pytest.raises(RuleError, match="unknown feature"):
        RuleStrategy(rule(conditions=[{"feature": "secret_sauce", "op": ">", "value": 1}]))
    with pytest.raises(RuleError, match="pick for ou"):
        RuleStrategy(rule(pick="home"))
    with pytest.raises(RuleError, match="id"):
        RuleStrategy(rule(id="Bad ID!"))


def test_rule_missing_feature_is_false(conn):
    s = RuleStrategy(rule())
    f = features.compute(conn, "Nobody", "Else", iso(KICKOFF), line=5.5)
    assert s.evaluate(offer(), f) is None


def test_loader_reads_rules_and_plugins(tmp_path):
    lab, plugins = tmp_path / "lab", tmp_path / "plugins"
    save_rule(lab, rule())
    plugins.mkdir()
    (plugins / "good.py").write_text(
        "from signal_pipeline.strategies import Strategy\n"
        "class P(Strategy):\n    id = 'plug'\n    def evaluate(self, o, f):\n        return None\n"
    )
    (plugins / "broken.py").write_text("raise RuntimeError('boom')\n")
    result = load_all(lab, plugins)
    assert sorted(s.id for s in result.strategies) == ["plug", "test-rule"]
    assert any("boom" in e for e in result.errors.values())


# --- engine ------------------------------------------------------------------------------


def test_engine_signals_once_and_sends(seeded):
    sent = []
    sink = TelegramSink(
        "token", Routing(default="-100"), post=lambda url, data: sent.append(data) or {"ok": True}
    )
    strategies = [RuleStrategy(rule())]
    src = FixedSource([offer(), offer(pick="under")])
    now = KICKOFF - timedelta(hours=1)
    first = run_cycle(seeded, src, strategies, sink, DEFAULT_SESSIONS, now=now)
    second = run_cycle(seeded, src, strategies, sink, DEFAULT_SESSIONS, now=now)
    assert len(first.new_signals) == 1 and second.new_signals == []
    assert len(sent) == 1 and "Ann vs Bob" in sent[0]["text"]
    row = seeded.execute("SELECT * FROM signals").fetchone()
    assert row["sent_at"] and row["send_error"] is None
    assert json.loads(row["details"])["features"]["h2h_n"] == 10


def test_engine_skips_started_matches(seeded):
    report = run_cycle(
        seeded, FixedSource([offer()]), [RuleStrategy(rule())], None, DEFAULT_SESSIONS, now=KICKOFF
    )
    assert report.new_signals == []


def test_engine_survives_broken_strategy(seeded):
    class Broken(RuleStrategy):
        def evaluate(self, o, f):
            raise ZeroDivisionError("oops")

    report = run_cycle(
        seeded,
        FixedSource([offer()]),
        [Broken(rule(id="broken")), RuleStrategy(rule())],
        None,
        DEFAULT_SESSIONS,
        now=KICKOFF - timedelta(hours=1),
    )
    assert "broken" in report.strategy_errors and len(report.new_signals) == 1


def test_unrouted_signal_is_not_sent():
    sink = TelegramSink("token", Routing(), post=lambda u, d: pytest.fail("should not send"))
    assert sink.send("x", "day", "hi") is None


def test_routing_precedence():
    r = Routing(default="d", by_session={"night": "n"}, by_strategy={"s": "x"})
    assert r.chat_for("s", "night") == "x"
    assert r.chat_for("other", "night") == "n"
    assert r.chat_for("other", "day") == "d"


# --- resolver ----------------------------------------------------------------------------


def test_resolver_settles_from_results(seeded):
    run_cycle(
        seeded,
        FixedSource([offer()]),
        [RuleStrategy(rule())],
        None,
        DEFAULT_SESSIONS,
        now=KICKOFF - timedelta(hours=1),
    )
    # result arrives with the players in reverse order and a 5-minute kick-off difference
    upsert_matches(seeded, [match(500, "Bob", "Ann", 1, 5, at=KICKOFF + timedelta(minutes=5))])
    counts = resolve_pending(seeded, now=KICKOFF + timedelta(hours=1))
    assert counts["won"] == 1
    row = seeded.execute("SELECT status, score1, score2 FROM signals").fetchone()
    assert (row["status"], row["score1"], row["score2"]) == ("won", 5, 1)
    [summary] = summarise(seeded)
    assert summary.won == 1 and summary.units == pytest.approx(0.9)


def test_resolver_voids_after_a_day(seeded):
    run_cycle(
        seeded,
        FixedSource([offer()]),
        [RuleStrategy(rule())],
        None,
        DEFAULT_SESSIONS,
        now=KICKOFF - timedelta(hours=1),
    )
    assert resolve_pending(seeded, now=KICKOFF + timedelta(hours=2))["waiting"] == 1
    assert resolve_pending(seeded, now=KICKOFF + timedelta(hours=25))["void"] == 1


# --- backtest ----------------------------------------------------------------------------


def test_backtest_counts_without_lookahead(seeded):
    s = RuleStrategy(rule(conditions=[{"feature": "h2h_n", "op": ">=", "value": 3}]))
    r = backtest.run(seeded, s, date_from="2026-01-01", date_to="2026-01-31", assumed_odds=2.0)
    # meetings 4..10 have ≥3 earlier meetings; totals: 7,7,7 then 3,3,3,3 → 3 won, 4 lost
    assert (r.signals, r.won, r.lost) == (7, 3, 4)
    assert r.break_even_odds == pytest.approx(7 / 3)
    assert r.units == pytest.approx(3 * 1.0 - 4)


# --- odds sources ------------------------------------------------------------------------


def test_demo_source_is_stable_and_complete(conn):
    src = DemoOddsSource(conn)
    a, b = src.fetch(), src.fetch()
    assert a and [o.key for o in a] == [o.key for o in b]
    assert {o.market for o in a} == {"ou", "1x2"}


def test_load_source_rejects_bad_spec():
    with pytest.raises(ValueError):
        load_source("no_colon_here")
    assert isinstance(load_source("signal_pipeline.odds.demo:DemoOddsSource"), DemoOddsSource)
