# Writing strategies

A strategy looks at one offer plus its features and decides whether to signal it. There are two
ways to write one, and both load side by side.

## 1. In the Strategy Lab (no code)

Open the dashboard (`python -m signal_pipeline ui`) → **Stratégia labor**. Pick a market and a
pick, optional filters (format, session, odds range), and add conditions. All conditions must
hold. Saving writes a JSON rule to `data/lab_strategies/<id>.json`, and the pipeline reloads it.

The same JSON can be written by hand:

```json
{
  "id": "h2h-over-demo",
  "name": "H2H over demo",
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
```

A condition on a feature that has no value (for example an over rate with no meetings) is
false, so a rule never fires by accident on missing data.

## 2. As a Python plugin

Drop a file into `strategies/` (or the folder `PIPELINE_STRATEGIES_DIR` points to). Every
`Strategy` subclass in it is loaded. See `strategies/example_h2h_edge.py`.

```python
from signal_pipeline.strategies.base import Decision, Strategy

class MyStrategy(Strategy):
    id = "my-strategy"          # stable: signals are keyed by it
    name = "My strategy"
    markets = ("1x2",)
    formats = ("12min",)

    def evaluate(self, offer, f):
        if offer.pick == "home" and f.h2h_n >= 10 and (f.h2h_p1_win_rate or 0) > 0.6:
            return Decision(reason=f"home won {f.h2h_p1_win_rate:.0%} of {f.h2h_n}")
        return None
```

A plugin that fails to import, or raises during `evaluate`, is reported on the dashboard and in
the log; the other strategies keep running.

## Features

Computed by `signal_pipeline.features.compute` **only from matches that finished before the
kick-off**, both live and in the backtest.

| Feature | Meaning |
|---|---|
| `h2h_n` | meetings in the H2H window |
| `h2h_avg_goals` | average total goals in those meetings |
| `h2h_over_rate` | share of meetings above the offer's line (O/U only) |
| `h2h_btts_rate` | share where both scored |
| `h2h_p1_win_rate`, `h2h_draw_rate`, `h2h_p2_win_rate` | results from player 1's side |
| `p1_n`, `p1_avg_scored`, `p1_avg_conceded` | player 1's last matches (form window) |
| `p2_n`, `p2_avg_scored`, `p2_avg_conceded` | player 2's last matches |
| `odds`, `implied_prob` | the offered price and 1 / price |
| `line` | the O/U line |

## Backtesting

There is no historical odds data, so the backtest replays past matches at an **assumed** price
and reports the hit rate and the **break-even odds**. Compare that with the prices you actually
get; the "units" number is only as real as the assumed price.

```
python -m signal_pipeline backtest my-strategy --from 2026-10-01 --to 2026-10-31 --line 5.5 --odds 1.85
```
