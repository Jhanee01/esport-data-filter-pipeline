"""Settling a pick against a final score. One place, used by the resolver and the backtest."""

from __future__ import annotations

MARKETS = ("ou", "1x2", "btts")
PICKS = {"ou": ("over", "under"), "1x2": ("home", "draw", "away"), "btts": ("yes", "no")}


def settle(market: str, pick: str, line: float | None, score1: int, score2: int) -> str:
    """Return 'won', 'lost' or 'push' (stake back, only on whole-number O/U lines)."""
    if market == "ou":
        if line is None:
            raise ValueError("an O/U pick needs a line")
        total = score1 + score2
        if total == line:
            return "push"
        over = total > line
        return "won" if (over if pick == "over" else not over) else "lost"
    if market == "1x2":
        result = "home" if score1 > score2 else "away" if score2 > score1 else "draw"
        return "won" if pick == result else "lost"
    if market == "btts":
        both = score1 > 0 and score2 > 0
        return "won" if both == (pick == "yes") else "lost"
    raise ValueError(f"unknown market: {market}")


def profit(status: str, odds: float | None, stake: float = 1.0) -> float:
    """Profit in units for a settled pick (0 for push/void, -stake for a loss)."""
    if status == "won":
        return (odds - 1.0) * stake if odds else 0.0
    if status == "lost":
        return -stake
    return 0.0
