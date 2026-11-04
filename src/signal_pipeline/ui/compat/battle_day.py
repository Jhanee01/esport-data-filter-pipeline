"""Battle day helpers with the original names, working on the tips that tips_reader builds."""

from ...battle_day import today_battle_day


def current_battle_day(now=None) -> str:
    return today_battle_day(now)


def tip_battle_day(tip: dict) -> str | None:
    return (tip.get("_raw") or {}).get("battle_day")


def tip_is_night(tip: dict) -> bool:
    return (tip.get("_raw") or {}).get("session") == "night"


def tip_session(tip: dict) -> str:
    return (tip.get("_raw") or {}).get("session") or "day"
