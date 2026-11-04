from datetime import UTC, datetime, timedelta

from conftest import match

from signal_pipeline.collectors import battle_api, history
from signal_pipeline.config import DEFAULT_SESSIONS
from signal_pipeline.store import connect, upsert_matches


def _api_match(mid, status, when, s1=None, s2=None):
    return {
        "id": mid,
        "status_id": status,
        "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "participant1": {"nickname": "Ann", "score": s1, "team": {"token_international": "Red"}},
        "participant2": {"nickname": "Bob", "score": s2, "team": {"token_international": "Blue"}},
    }


def test_parse_tournament_splits_results_and_fixtures():
    now = datetime.now(UTC)
    t = {
        "id": 7,
        "start_date": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "token_international": "Battle League",
        "location": {"token": "Anfield"},
    }
    matches = [
        _api_match(1, 3, now - timedelta(minutes=50), 3, 2),
        _api_match(2, 1, now + timedelta(minutes=30)),
        {"id": 3, "broken": True},
    ]
    results, fixtures = battle_api.parse_tournament(t, matches, DEFAULT_SESSIONS)
    assert [r["id"] for r in results] == [1] and results[0]["format"] == "12min"
    assert (results[0]["score1"], results[0]["team1"]) == (3, "Red")
    assert [f["id"] for f in fixtures] == [2]


def test_import_from_mcp_database(tmp_path, conn):
    mcp = connect(tmp_path / "mcp.db")  # same matches schema as esoccer-battle-mcp
    upsert_matches(mcp, [match(i, "Ann", "Bob", 1, 1) for i in range(5)])
    mcp.close()
    assert history.import_from_db(conn, tmp_path / "mcp.db") == 5
    assert history.import_from_db(conn, tmp_path / "mcp.db") == 0  # idempotent
