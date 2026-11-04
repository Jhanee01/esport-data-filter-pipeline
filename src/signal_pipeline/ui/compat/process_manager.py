"""The components the dashboard shows as status cards (the original listed its processes)."""

PROCESSES = {
    "pipeline": {"label": "Jelzés-motor"},
    "results": {"label": "Battle gyűjtő"},
    "odds": {"label": "Odds-forrás"},
    "strategies": {"label": "Stratégiák"},
    "telegram": {"label": "Telegram"},
}

# Cards with a start/stop button (the others only show their state).
TOGGLEABLE = {"pipeline"}
