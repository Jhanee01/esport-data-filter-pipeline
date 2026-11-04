"""Odds sources. The repo ships only a demo source; real ones are private plugins."""

from .base import OddsSource, Offer, load_source

__all__ = ["Offer", "OddsSource", "load_source"]
