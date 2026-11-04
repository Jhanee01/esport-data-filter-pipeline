"""The odds source interface: where the pipeline gets prices from.

A real bookmaker scraper is NOT part of this repo. Write your own class with the same
interface (see docs/writing-an-odds-source.md) and point ODDS_SOURCE at it, e.g.
`ODDS_SOURCE=my_private_plugins.mybook:MyBookSource`.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Offer:
    """One price for one pick on one match, e.g. over 5.5 at 1.85."""

    source: str
    kickoff_utc: str  # ISO 8601, UTC
    player1: str
    player2: str
    market: str  # "ou" | "1x2" | "btts"
    pick: str  # over/under, home/draw/away, yes/no
    odds: float
    line: float | None = None  # O/U only
    venue: str | None = None
    format: str | None = None  # "8min" | "12min"
    team1: str | None = None
    team2: str | None = None

    @property
    def key(self) -> str:
        """Stable identity of the offer. The engine signals each (strategy, key) only once."""
        line = "" if self.line is None else f"{self.line:g}"
        return "|".join(
            (
                self.source,
                self.kickoff_utc,
                self.player1.lower(),
                self.player2.lower(),
                self.market,
                line,
                self.pick,
            )
        )

    def as_dict(self) -> dict:
        return {**asdict(self), "key": self.key}


class OddsSource(ABC):
    """Implement `fetch()` to return the currently open offers."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> list[Offer]:
        """Return the offers that are open right now. Must not raise on a transient
        network error: log it and return what you have (or an empty list)."""

    def close(self) -> None:  # noqa: B027 - optional hook, a no-op by default
        """Release browsers, sessions, files. Called once on shutdown."""


def load_source(spec: str, **kwargs) -> OddsSource:
    """Load an OddsSource from 'package.module:ClassName'."""
    module_name, _, class_name = spec.partition(":")
    if not class_name:
        raise ValueError(f"ODDS_SOURCE must look like 'module:Class', got {spec!r}")
    cls = getattr(importlib.import_module(module_name), class_name)
    source = cls(**kwargs)
    if not isinstance(source, OddsSource):
        raise TypeError(f"{spec} is not an OddsSource")
    return source
