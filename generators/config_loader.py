from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_generator_config(path: str | Path) -> dict[str, Any]:
    """Load generator config from JSON, with optional YAML support."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    suffix = config_path.suffix.lower()
    if suffix == ".json":
        return json.loads(config_path.read_text(encoding="utf-8"))

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "YAML config requested, but PyYAML is not installed. "
                "Use JSON config or install PyYAML."
            ) from exc
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError("YAML config must contain a top-level mapping/object.")
        return data

    raise ValueError(f"Unsupported config extension: {suffix}. Use .json or .yaml/.yml")
