from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .baseline import baseline_value, build_usage_series
from .config_loader import load_generator_config
from .injectors import apply_budget_breach, apply_drift, apply_level_shift, apply_spike
from .labels import build_labels
from .noise import build_gaussian_noise
from .trend_seasonality import build_seasonality_component, build_trend_component

CANONICAL_FIELDS = [
    "event_id",
    "timestamp",
    "provider",
    "account_id",
    "service",
    "region",
    "cost_amount",
    "usage_amount",
    "usage_unit",
    "tags",
    "source_type",
]


def _normalize_start_time(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _steps_per_day(freq: str) -> int:
    delta = pd.to_timedelta(freq)
    if delta <= pd.Timedelta(0):
        raise ValueError("frequency must be a positive pandas offset string.")
    return max(1, int(pd.Timedelta(days=1) / delta))


def _generate_tags(
    n: int,
    rng: np.random.Generator,
    tags_cfg: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if not tags_cfg:
        return [{} for _ in range(n)]

    enabled = bool(tags_cfg.get("enabled", False))
    if not enabled:
        return [{} for _ in range(n)]

    base = dict(tags_cfg.get("base", {}))
    options = tags_cfg.get("options", {})

    tags: list[dict[str, str]] = []
    for _ in range(n):
        current = dict(base)
        for key, values in options.items():
            if isinstance(values, list) and values:
                current[str(key)] = str(rng.choice(values))
        tags.append(current)
    return tags


def _validate_canonical_schema(df: pd.DataFrame) -> None:
    if list(df.columns) != CANONICAL_FIELDS:
        raise ValueError(f"Schema mismatch. Expected columns: {CANONICAL_FIELDS}")
    if (df["cost_amount"] < 0).any():
        raise ValueError("cost_amount contains negative values.")
    if (df["usage_amount"] < 0).any():
        raise ValueError("usage_amount contains negative values.")


def _build_base_dataframe(config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    n = int(config.get("n", 100))
    if n <= 0:
        raise ValueError("n must be > 0")

    seed = config.get("seed")
    rng = np.random.default_rng(seed)

    start_time = _normalize_start_time(str(config["start_time"]))
    freq = str(config.get("frequency", "1H"))
    timestamps = pd.date_range(start=start_time, periods=n, freq=freq)

    accounts = list(config.get("accounts", []))
    services = list(config.get("services", []))
    regions = list(config.get("regions", []))
    usage_units = list(config.get("usage_units", ["unit"]))

    if not accounts or not services or not regions:
        raise ValueError("accounts, services, and regions must be non-empty.")

    account_ids = rng.choice(accounts, size=n, replace=True).astype(str)
    service_vals = rng.choice(services, size=n, replace=True).astype(str)
    region_vals = rng.choice(regions, size=n, replace=True).astype(str)
    usage_unit_vals = rng.choice(usage_units, size=n, replace=True).astype(str)

    baseline_cfg = config.get("baseline", {})
    default_baseline = float(baseline_cfg.get("default", 100.0))
    by_account = baseline_cfg.get("by_account", {})
    baseline_series = np.array(
        [baseline_value(acc, by_account, default_baseline) for acc in account_ids],
        dtype=float,
    )

    trend_component = build_trend_component(n=n, trend_cfg=config.get("trend"))
    seasonality_component = build_seasonality_component(
        n=n,
        seasonality_cfg=config.get("seasonality"),
        steps_per_day=_steps_per_day(freq),
    )
    noise = build_gaussian_noise(n=n, noise_cfg=config.get("noise"), rng=rng)

    cost_series = baseline_series * trend_component * seasonality_component + noise
    cost_series = np.clip(cost_series, 0.0, None)

    usage_cfg = config.get("usage", {})
    usage_mean = float(usage_cfg.get("mean", 100.0))
    usage_std = float(usage_cfg.get("std", 10.0))
    usage_series = build_usage_series(n=n, rng=rng, mean=usage_mean, std=usage_std)

    injectors_cfg = config.get("anomaly_injectors", {})
    budget_cfg = injectors_cfg.get("budget_breach", {})
    default_budget = float(np.nanmean(cost_series))
    if np.isnan(default_budget):
        default_budget = 1000.0
    budget_threshold = float(budget_cfg.get("budget_threshold", default_budget))
    if np.isnan(budget_threshold):
        budget_threshold = 1000.0

    cost_series, spike_mask = apply_spike(cost_series, injectors_cfg.get("spike"), rng)
    cost_series, drift_mask = apply_drift(cost_series, injectors_cfg.get("drift"))
    cost_series, level_shift_mask = apply_level_shift(cost_series, injectors_cfg.get("level_shift"))
    cost_series, budget_mask = apply_budget_breach(cost_series, budget_cfg, budget_threshold)

    cost_series = np.clip(cost_series, 0.0, None)
    usage_series = np.clip(usage_series, 0.0, None)

    tags = _generate_tags(n=n, rng=rng, tags_cfg=config.get("tags"))

    df = pd.DataFrame(
        {
            "event_id": [str(uuid.uuid4()) for _ in range(n)],
            "timestamp": [ts.isoformat() for ts in timestamps],
            "provider": str(config.get("provider", "gcp")),
            "account_id": account_ids,
            "service": service_vals,
            "region": region_vals,
            "cost_amount": cost_series.astype(float),
            "usage_amount": usage_series.astype(float),
            "usage_unit": usage_unit_vals,
            "tags": tags,
            "source_type": str(config.get("source_type", "synthetic")),
        }
    )

    injector_masks = {
        "spike": spike_mask,
        "drift": drift_mask,
        "level_shift": level_shift_mask,
        "budget_breach": budget_mask,
    }
    return df, injector_masks


def generate_labeled_events_dataframe(config: dict[str, Any]) -> pd.DataFrame:
    """Generate events with anomaly labels appended."""
    df, injector_masks = _build_base_dataframe(config)
    labels = build_labels(injector_masks, len(df))
    labeled = pd.concat([df, labels], axis=1)
    return labeled


def generate_events_dataframe(config: dict[str, Any]) -> pd.DataFrame:
    """Generate events in strict canonical schema only."""
    df, _ = _build_base_dataframe(config)
    df = df[CANONICAL_FIELDS].copy()
    _validate_canonical_schema(df)
    return df


def generate_labeled_events_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    return generate_labeled_events_dataframe(config).to_dict(orient="records")


def generate_events_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    return generate_events_dataframe(config).to_dict(orient="records")


def load_and_generate_events_dataframe(config_path: str | Path) -> pd.DataFrame:
    config = load_generator_config(config_path)
    return generate_events_dataframe(config)


def load_and_generate_labeled_events_dataframe(config_path: str | Path) -> pd.DataFrame:
    config = load_generator_config(config_path)
    return generate_labeled_events_dataframe(config)


def export_events_jsonl(
    events: pd.DataFrame | list[dict[str, Any]],
    output_path: str | Path,
) -> Path:
    """Write one JSON object per line."""
    if isinstance(events, pd.DataFrame):
        records = events.to_dict(orient="records")
    else:
        records = events

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=True, default=str))
            handle.write("\n")
    return out_path
