"""Telegram output with per-strategy and per-session channel routing.

routing.json:

    {
      "default": "",
      "by_session": {"night": "-100…"},
      "by_strategy": {"my-rule": "-100…"}
    }

The most specific match wins: strategy → session → default. An empty chat id means the
signal is only recorded locally, not sent. Chat ids live in data/, never in the repo.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_PICK_LABEL = {
    "over": "Over",
    "under": "Under",
    "home": "Home",
    "draw": "Draw",
    "away": "Away",
    "yes": "BTTS yes",
    "no": "BTTS no",
}


@dataclass
class Routing:
    default: str = ""
    by_session: dict[str, str] = field(default_factory=dict)
    by_strategy: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Routing:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            default=raw.get("default", ""),
            by_session=raw.get("by_session", {}),
            by_strategy=raw.get("by_strategy", {}),
        )

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {"default": self.default, "by_session": self.by_session, "by_strategy": self.by_strategy},
                indent=2,
            ),
            encoding="utf-8",
        )

    def chat_for(self, strategy_id: str, session: str | None) -> str:
        return (
            self.by_strategy.get(strategy_id)
            or (self.by_session.get(session) if session else None)
            or self.default
        )


def format_signal(strategy_name: str, offer: dict, reason: str, kickoff_local: str) -> str:
    pick = _PICK_LABEL.get(offer["pick"], offer["pick"])
    line = f" {offer['line']:g}" if offer.get("line") is not None else ""
    where = " · ".join(x for x in (offer.get("venue"), offer.get("format")) if x)
    return (
        f"📊 {strategy_name}\n"
        f"{kickoff_local}  {offer['player1']} vs {offer['player2']}\n"
        f"{where}\n"
        f"➡️ {pick}{line} @ {offer['odds']:.2f}\n"
        f"{reason}"
    )


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
        return json.loads(r.read())


class TelegramSink:
    def __init__(self, token: str | None, routing: Routing, post: Callable[[str, dict], dict] = _post):
        self.token = token
        self.routing = routing
        self._post = post

    def send(self, strategy_id: str, session: str | None, text: str) -> str | None:
        """Send if routed. Returns None on success or when not routed, else an error message."""
        chat = self.routing.chat_for(strategy_id, session)
        if not chat:
            return None
        if not self.token:
            return "TELEGRAM_TOKEN is not set"
        try:
            reply = self._post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                {"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
            )
            return None if reply.get("ok") else f"Telegram: {reply.get('description', 'not ok')}"
        except Exception as e:  # network errors must not stop the engine
            log.warning("telegram send failed: %s", e)
            return f"{type(e).__name__}: {e}"
