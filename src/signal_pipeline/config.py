"""Settings, paths and environment.

Everything that differs between machines comes from environment variables (or a
`.env` file next to the working directory). Nothing secret is ever written to the repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments. Existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    strategies_dir: Path
    telegram_token: str | None
    remote_token: str | None
    remote_port: int
    odds_source: str
    poll_seconds: int
    sessions: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pipeline.db"

    @property
    def routing_path(self) -> Path:
        return self.data_dir / "routing.json"

    @property
    def lab_dir(self) -> Path:
        """Strategies created in the Strategy Lab (JSON rules)."""
        return self.data_dir / "lab_strategies"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "pipeline.log"


# Session windows in Europe/Budapest local time. A Battle day runs 06:00 → 06:00.
DEFAULT_SESSIONS = {
    "day": ("06:00", "14:00"),
    "afternoon": ("14:00", "22:00"),
    "night": ("22:00", "06:00"),
}


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or Path.cwd() / ".env")
    data_dir = Path(os.environ.get("PIPELINE_DATA_DIR", Path.cwd() / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        strategies_dir=Path(os.environ.get("PIPELINE_STRATEGIES_DIR", Path.cwd() / "strategies")),
        telegram_token=os.environ.get("TELEGRAM_TOKEN") or None,
        remote_token=os.environ.get("REMOTE_TOKEN") or None,
        remote_port=int(os.environ.get("REMOTE_PORT", "8765")),
        odds_source=os.environ.get("ODDS_SOURCE", "signal_pipeline.odds.demo:DemoOddsSource"),
        poll_seconds=int(os.environ.get("POLL_SECONDS", "30")),
        sessions=DEFAULT_SESSIONS,
    )
