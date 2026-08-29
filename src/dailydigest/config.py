"""Config loading. Config is data — see config/digest.yaml."""

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_config(path: str | Path = "config/digest.yaml") -> dict[str, Any]:
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
