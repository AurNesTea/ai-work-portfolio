from __future__ import annotations

import importlib.resources
from pathlib import Path


def dispatch_rules_path() -> Path:
    try:
        traversable = importlib.resources.files("aiwork").joinpath("resources", "dispatch-rules.md")
        p = Path(str(traversable))
        if p.is_file():
            return p.resolve()
    except Exception:
        pass

    pkg_root = Path(__file__).resolve().parent
    fallback = pkg_root / "resources" / "dispatch-rules.md"
    if fallback.is_file():
        return fallback.resolve()
    raise FileNotFoundError("dispatch-rules.md not found in aiwork resources")
