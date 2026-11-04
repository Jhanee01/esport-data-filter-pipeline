"""EXAMPLE plugin strategy — shows the interface, it is not a tested or profitable strategy.

It signals an O/U "over" when the players' recent meetings went over the line noticeably
more often than the price implies. Copy this file, rename the class and the id, and write
your own logic in `evaluate`.
"""

from signal_pipeline.features import Features
from signal_pipeline.odds.base import Offer
from signal_pipeline.strategies.base import Decision, Strategy


class ExampleH2HEdge(Strategy):
    id = "example-h2h-edge"
    name = "Example: H2H over rate vs. price"
    markets = ("ou",)
    min_odds = 1.4
    h2h_window = 20

    MIN_MEETINGS = 8
    MIN_EDGE = 0.10  # over rate must beat the implied probability by this much

    def wants(self, offer: Offer, session: str | None) -> bool:
        return offer.pick == "over" and super().wants(offer, session)

    def evaluate(self, offer: Offer, f: Features) -> Decision | None:
        if f.h2h_n < self.MIN_MEETINGS or f.h2h_over_rate is None or f.implied_prob is None:
            return None
        edge = f.h2h_over_rate - f.implied_prob
        if edge < self.MIN_EDGE:
            return None
        return Decision(
            reason=f"H2H over {f.h2h_over_rate:.0%} in {f.h2h_n} meetings vs. {f.implied_prob:.0%} implied",
            details={"edge": round(edge, 3)},
        )
