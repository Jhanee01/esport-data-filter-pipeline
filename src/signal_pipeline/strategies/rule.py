"""Rule strategies: the JSON format the Strategy Lab writes.

Example (data/lab_strategies/my-rule.json):

    {
      "id": "my-rule",
      "name": "My rule",
      "enabled": true,
      "market": "ou",
      "pick": "over",
      "formats": ["8min"],
      "sessions": null,
      "min_odds": 1.5,
      "max_odds": 3.0,
      "h2h_window": 20,
      "form_window": 10,
      "conditions": [
        {"feature": "h2h_n", "op": ">=", "value": 10},
        {"feature": "h2h_over_rate", "op": ">=", "value": 0.6}
      ]
    }

All conditions must hold (AND). A condition on a feature that has no value (for example an
over rate when there are no meetings) is false, never true by accident.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass

from ..features import FEATURE_NAMES, Features
from ..markets import PICKS
from ..odds.base import Offer
from .base import Decision, Strategy

OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Condition:
    feature: str
    op: str
    value: float

    def holds(self, features: Features) -> bool:
        actual = getattr(features, self.feature)
        return actual is not None and OPS[self.op](actual, self.value)

    def describe(self, features: Features) -> str:
        actual = getattr(features, self.feature)
        shown = "—" if actual is None else (f"{actual:.2f}" if isinstance(actual, float) else str(actual))
        return f"{self.feature} {self.op} {self.value:g} ({shown})"


class RuleStrategy(Strategy):
    def __init__(self, spec: dict):
        self.spec = validate(spec)
        self.id = spec["id"]
        self.name = spec.get("name") or spec["id"]
        self.enabled = bool(spec.get("enabled", True))
        self.market = spec["market"]
        self.pick = spec["pick"]
        self.markets = (self.market,)
        self.formats = tuple(spec["formats"]) if spec.get("formats") else None
        self.sessions = tuple(spec["sessions"]) if spec.get("sessions") else None
        self.min_odds = spec.get("min_odds")
        self.max_odds = spec.get("max_odds")
        self.h2h_window = int(spec.get("h2h_window", 20))
        self.form_window = int(spec.get("form_window", 10))
        self.conditions = [
            Condition(c["feature"], c["op"], float(c["value"])) for c in spec.get("conditions", [])
        ]

    def wants(self, offer: Offer, session: str | None) -> bool:
        return offer.pick == self.pick and super().wants(offer, session)

    def evaluate(self, offer: Offer, features: Features) -> Decision | None:
        if not all(c.holds(features) for c in self.conditions):
            return None
        return Decision(
            reason="; ".join(c.describe(features) for c in self.conditions) or "no conditions",
            details={"rule": self.id},
        )


def validate(spec: dict) -> dict:
    """Raise RuleError with a message the Strategy Lab can show as-is."""
    if not isinstance(spec, dict):
        raise RuleError("a rule must be a JSON object")
    sid = spec.get("id", "")
    if not isinstance(sid, str) or not _ID.match(sid):
        raise RuleError("id: 2–64 characters, lowercase letters, digits, '-' or '_'")
    market = spec.get("market")
    if market not in PICKS:
        raise RuleError(f"market must be one of {sorted(PICKS)}")
    if spec.get("pick") not in PICKS[market]:
        raise RuleError(f"pick for {market} must be one of {list(PICKS[market])}")
    for key in ("min_odds", "max_odds"):
        v = spec.get(key)
        if v is not None and (not isinstance(v, (int, float)) or v < 1.0):
            raise RuleError(f"{key} must be a number ≥ 1.0 or null")
    for key in ("h2h_window", "form_window"):
        v = spec.get(key, 10)
        if not isinstance(v, int) or not 1 <= v <= 500:
            raise RuleError(f"{key} must be a whole number between 1 and 500")
    conditions = spec.get("conditions", [])
    if not isinstance(conditions, list):
        raise RuleError("conditions must be a list")
    for i, c in enumerate(conditions, 1):
        if not isinstance(c, dict) or c.get("feature") not in FEATURE_NAMES:
            raise RuleError(f"condition {i}: unknown feature (allowed: {', '.join(FEATURE_NAMES)})")
        if c.get("op") not in OPS:
            raise RuleError(f"condition {i}: op must be one of {list(OPS)}")
        if not isinstance(c.get("value"), (int, float)):
            raise RuleError(f"condition {i}: value must be a number")
    return spec
