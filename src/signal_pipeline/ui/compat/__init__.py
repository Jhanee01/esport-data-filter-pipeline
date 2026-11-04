"""Compatibility layer for the dashboard views taken over from the original tool.

The original views read their data through a handful of modules (`config`,
`core.stats_manager`, `core.tips_reader`, `core.feed_watcher`, `core.process_manager`, ...).
These modules keep the same names and data shapes, but read from the pipeline's SQLite
database instead of the original JSON / CSV files, so the views themselves stay as they were.
"""
