"""Loading strategies from the two places they can live.

- `<data>/lab_strategies/*.json` — rules saved by the Strategy Lab
- `<strategies dir>/*.py`         — Python plugins: any `Strategy` subclass defined in the file
                                    (or instances listed in a module-level `STRATEGIES`)

A broken file never stops the others from loading: its error is returned so the dashboard
can show it.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .base import Strategy
from .rule import RuleError, RuleStrategy, validate


@dataclass
class LoadResult:
    strategies: list[Strategy] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # file → message


def save_rule(lab_dir: Path, spec: dict) -> Path:
    validate(spec)
    lab_dir.mkdir(parents=True, exist_ok=True)
    path = lab_dir / f"{spec['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def delete_rule(lab_dir: Path, strategy_id: str) -> bool:
    path = lab_dir / f"{strategy_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def _load_rules(lab_dir: Path, result: LoadResult) -> None:
    if not lab_dir.exists():
        return
    for path in sorted(lab_dir.glob("*.json")):
        try:
            result.strategies.append(RuleStrategy(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, RuleError) as e:
            result.errors[str(path)] = str(e)


def _load_plugins(plugin_dir: Path, result: LoadResult) -> None:
    if not plugin_dir.exists():
        return
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = f"pipeline_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            found = list(getattr(module, "STRATEGIES", []))
            if not found:
                found = [
                    cls()
                    for _, cls in inspect.getmembers(module, inspect.isclass)
                    if issubclass(cls, Strategy) and cls.__module__ == name and not inspect.isabstract(cls)
                ]
            for s in found:
                if not s.id:
                    raise ValueError(f"{type(s).__name__} has no id")
            result.strategies.extend(found)
        except Exception as e:  # a plugin can fail in any way; report it, keep going
            result.errors[str(path)] = f"{type(e).__name__}: {e}"


def load_all(lab_dir: Path, plugin_dir: Path) -> LoadResult:
    result = LoadResult()
    _load_rules(lab_dir, result)
    _load_plugins(plugin_dir, result)
    seen: set[str] = set()
    for s in list(result.strategies):
        if s.id in seen:
            result.strategies.remove(s)
            result.errors[s.id] = f"duplicate strategy id {s.id!r}; the later one was skipped"
        seen.add(s.id)
    return result
