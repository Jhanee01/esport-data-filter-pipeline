from conftest import match

from signal_pipeline.schedule import Schedule, _day_minutes, block_status
from signal_pipeline.store import upsert_matches

DAY = "2026-11-03"


def test_classify_by_block_start():
    s = Schedule.bundled()
    assert s.classify("Stamford Bridge", DAY, "06:30") == (1, "day")
    assert s.classify("Wembley", DAY, "22:12") == (8, "night")     # within tolerance
    assert s.classify("Anfield", DAY, "17:50") == (5, "afternoon")
    assert s.classify("Nowhere", DAY, "10:00") == (None, None)


def test_blocks_cover_both_formats_and_cross_midnight():
    blocks = Schedule.bundled().blocks(DAY)
    assert {b.format for b in blocks} == {"8min", "12min"}
    t10 = next(b for b in blocks if b.venue == "Stamford Bridge" and b.turnus == 10)
    assert t10.start == "02:00" and t10.start_min > _day_minutes("23:50")   # after midnight sorts last


def test_block_status(conn):
    row = match(1, "Ann", "Bob", 2, 1)
    row.update(battle_day=DAY, venue="Stamford Bridge", local_time="06:40")
    upsert_matches(conn, [row])
    st = block_status(conn, DAY, now_min=_day_minutes("12:00"))
    assert st[("Stamford Bridge", 1)] == "done"
    assert st[("Old Trafford", 1)] == "overdue"
    assert st[("Stamford Bridge", 5)] == "pending"
    assert block_status(conn, DAY, now_min=_day_minutes("06:50"))[("Stamford Bridge", 1)] == "running"
