"""The running Pipeline the compatibility modules read from (set by the app at startup)."""

PIPELINE = None


def pipeline():
    if PIPELINE is None:
        raise RuntimeError("the dashboard needs a running Pipeline (compat.runtime.PIPELINE)")
    return PIPELINE
