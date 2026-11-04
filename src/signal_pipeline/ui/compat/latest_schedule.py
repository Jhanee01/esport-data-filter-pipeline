"""The original core.latest_schedule interface (San Siro blocks), backed by the bundled schedule."""

from .turnus import LATEST_VENUE as VENUE
from .turnus import latest_blocks_for

__all__ = ["VENUE", "blocks_for"]


def blocks_for(day: str, fetch: bool = False) -> dict:
    return latest_blocks_for(day, fetch)
