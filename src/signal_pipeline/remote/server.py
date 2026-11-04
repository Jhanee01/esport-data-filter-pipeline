"""Phone remote: a small token-protected web page with the live log, health and a restart.

Meant to be reached over a private network such as Tailscale; it never needs an open port
on the router. Every request must carry the token (`?token=` or `Authorization: Bearer`).
"""

import hmac
import logging
import secrets
import threading
from importlib import resources

log = logging.getLogger(__name__)


def create_app(pipeline, token: str):
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="signal-pipeline remote", docs_url=None, redoc_url=None)

    def auth(request: Request) -> None:
        given = (
            request.query_params.get("token")
            or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        )
        if not given or not hmac.compare_digest(given, token):
            raise HTTPException(status_code=401, detail="bad token")

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def index() -> str:
        return resources.files("signal_pipeline.remote").joinpath("static/index.html").read_text("utf-8")

    @app.get("/api/status", dependencies=[Depends(auth)])
    def status() -> dict:
        last = pipeline.last_cycle
        return {
            "running": pipeline.running,
            "health": [c.__dict__ for c in pipeline.health()],
            "last_cycle": None
            if last is None
            else {"offers": last.offers, "new": len(last.new_signals), "errors": len(last.strategy_errors)},
            "log": list(pipeline.ring.lines)[-200:],
        }

    @app.post("/api/restart", dependencies=[Depends(auth)])
    def restart() -> dict:
        pipeline.stop()
        pipeline.reload_strategies()
        pipeline.start()
        return {"ok": True}

    return app


def serve_in_background(pipeline) -> threading.Thread:
    import uvicorn

    token = pipeline.settings.remote_token or secrets.token_urlsafe(24)
    if not pipeline.settings.remote_token:
        log.warning("REMOTE_TOKEN not set; generated one for this run: %s", token)
    port = pipeline.settings.remote_port
    log.info("remote page: http://127.0.0.1:%d/?token=<REMOTE_TOKEN>", port)
    config = uvicorn.Config(create_app(pipeline, token), host="0.0.0.0", port=port, log_level="warning")
    thread = threading.Thread(target=uvicorn.Server(config).run, name="remote", daemon=True)
    thread.start()
    return thread
