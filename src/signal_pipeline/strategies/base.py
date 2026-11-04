"""The strategy interface. A strategy looks at one offer plus its features and decides."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..features import Features
from ..odds.base import Offer


@dataclass(frozen=True)
class Decision:
    """A strategy's yes. `reason` ends up in the Telegram message and the signal log."""

    reason: str
    details: dict = field(default_factory=dict)


class Strategy(ABC):
    """Subclass this in a file under `strategies/` to write a strategy in Python.

    Set `id` (unique, stable: signals are keyed by it) and `name`, narrow the offers with
    `markets` / `formats` / `sessions`, and implement `evaluate`.
    """

    id: str = ""
    name: str = ""
    markets: tuple[str, ...] = ("ou", "1x2", "btts")
    formats: tuple[str, ...] | None = None  # None = all
    sessions: tuple[str, ...] | None = None  # None = all
    min_odds: float | None = None
    max_odds: float | None = None
    h2h_window: int = 20
    form_window: int = 10
    enabled: bool = True

    def wants(self, offer: Offer, session: str | None) -> bool:
        """Cheap pre-filter, so features are only computed for offers that can match."""
        if offer.market not in self.markets:
            return False
        if self.formats and offer.format not in self.formats:
            return False
        if self.sessions and session not in self.sessions:
            return False
        if self.min_odds is not None and offer.odds < self.min_odds:
            return False
        if self.max_odds is not None and offer.odds > self.max_odds:
            return False
        return True

    @abstractmethod
    def evaluate(self, offer: Offer, features: Features) -> Decision | None:
        """Return a Decision to signal this offer, or None to skip it."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id!r}>"
