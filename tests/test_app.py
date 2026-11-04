"""Remote page and dashboard smoke tests. Skipped when the optional extras aren't installed."""

import os

import pytest

from signal_pipeline.config import load_settings
from signal_pipeline.odds.demo import DemoOddsSource


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIPELINE_STRATEGIES_DIR", str(tmp_path / "none"))
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    from signal_pipeline.service import Pipeline

    p = Pipeline(load_settings(env_file=tmp_path / "missing.env"), source=DemoOddsSource())
    yield p
    p.close()


def test_remote_requires_token(pipeline):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from signal_pipeline.remote.server import create_app

    client = TestClient(create_app(pipeline, "s3cret"))
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status?token=wrong").status_code == 401
    ok = client.get("/api/status", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and {c["name"] for c in ok.json()["health"]} >= {"results", "odds"}
    assert "Újraindítás" in client.get("/?token=s3cret").text


def test_pipeline_cycle_with_demo_source(pipeline):
    report = pipeline.cycle()
    assert report.offers > 0 and report.new_signals == []  # no strategies loaded


def test_dashboard_builds(pipeline):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from signal_pipeline.ui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(pipeline)
    window.refresh()
    assert window.windowTitle() == "Signal pipeline"
    window.timer.stop()
    window.deleteLater()
    app.processEvents()
