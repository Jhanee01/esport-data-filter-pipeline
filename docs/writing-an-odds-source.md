# Writing an odds source (bookmaker scraper)

The pipeline gets prices from an **odds source**: any class that implements
`signal_pipeline.odds.base.OddsSource`. The repo ships only `DemoOddsSource`, which invents
prices so the whole chain can run. A scraper for a real bookmaker is not included on
purpose: you write your own and keep it in a private package.

## The interface

```python
from signal_pipeline.odds.base import Offer, OddsSource

class MyBookSource(OddsSource):
    name = "mybook"            # goes into every offer key and the signal log

    def fetch(self) -> list[Offer]:
        ...                    # return every open price right now

    def close(self) -> None:
        ...                    # optional: quit the browser, close sessions
```

An `Offer` is one price for one pick:

| Field | Example | Notes |
|---|---|---|
| `kickoff_utc` | `"2026-11-04T19:40:00+00:00"` | ISO 8601 in UTC. The resolver matches results within ±20 min. |
| `player1`, `player2` | `"tizzy"`, `"Simaponika"` | Battle nicknames. Map the bookmaker's spelling to these. |
| `market` | `"ou"`, `"1x2"`, `"btts"` | |
| `pick` | `"over"`, `"under"`, `"home"`, `"draw"`, `"away"`, `"yes"`, `"no"` | |
| `line` | `5.5` | O/U only. |
| `odds` | `1.86` | Decimal odds. |
| `venue`, `format` | `"Wembley"`, `"8min"` | Optional, but strategies and the resolver use `format`. |

Return both sides of a market as separate offers (over **and** under). The engine signals each
`(strategy, offer.key)` pair only once, so returning the same open prices on every poll is fine.

## Rules for a well-behaved source

- **Don't raise on transient errors.** Log, and return what you have (or `[]`). The engine
  survives an exception, but a clean empty list keeps the health check honest.
- **Normalise names.** The most common failure is a nickname that differs between the bookmaker
  and the Battle results (case, suffixes, team in brackets). Resolve it inside `fetch()`.
- **Drop started matches.** The engine ignores anything kicking off within a minute anyway.
- **Be gentle.** Poll at the interval the pipeline asks for (`POLL_SECONDS`), reuse one browser
  session, and respect the site's terms of use. Whether you may scrape a site at all is your
  responsibility.

## Wiring it in

Put the class in an importable package (not in this repo), then:

```
ODDS_SOURCE=my_private_plugins.mybook:MyBookSource
```

If the constructor needs settings, read them from environment variables inside `__init__`.
The demo source is the only one that receives the database connection.

## A browser-based skeleton

```python
import logging
from playwright.sync_api import sync_playwright
from signal_pipeline.odds.base import Offer, OddsSource

log = logging.getLogger(__name__)

class MyBookSource(OddsSource):
    name = "mybook"

    def __init__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page()

    def fetch(self) -> list[Offer]:
        try:
            self._page.goto("https://…/esports-football", wait_until="networkidle")
            rows = self._page.locator("…").all()        # your selectors
        except Exception as e:
            log.warning("mybook fetch failed: %s", e)
            return []
        offers = []
        for row in rows:
            ...                                          # parse players, kick-off, line, prices
        return offers

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()
```
