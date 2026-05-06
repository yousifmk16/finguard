"""
TST-02: Unit tests for ml.src.training.versioning (TS-05).

Covers ModelVersionRegistry: register / load / list / prune flows plus
the manifest.json round-trip and the latest/ snapshot directory.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

# ml/src/training/__init__.py re-exports retrain.py which imports apscheduler.
# The TS-04 scheduler is not in scope for these unit tests, so stub the
# packages it pulls in before importing the versioning module.
def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


if "apscheduler" not in sys.modules:
    _stub("apscheduler")
    _stub("apscheduler.schedulers")
    bg = _stub("apscheduler.schedulers.background")
    bg.BackgroundScheduler = type("BackgroundScheduler", (), {})  # type: ignore[attr-defined]
    triggers = _stub("apscheduler.triggers")
    interval = _stub("apscheduler.triggers.interval")
    interval.IntervalTrigger = type("IntervalTrigger", (), {})  # type: ignore[attr-defined]

from ml.src.models.baseline import BaselineConfig, TimeSeriesBaselineModel  # noqa: E402
from ml.src.training.versioning import (  # noqa: E402
    ModelVersionRegistry,
    VersionEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_training_df(rows: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    start = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    out = []
    for i in range(rows):
        ts = start + timedelta(minutes=i)
        out.append({
            "bucket": ts,
            "account_id": "acct-1",
            "service": "compute",
            "region": "us-central1",
            "total_cost": 100.0 + rng.normal(0, 5),
            "hour_of_day": ts.hour,
            "day_of_week": ts.weekday(),
        })
    return pd.DataFrame(out)


def _fitted_model() -> TimeSeriesBaselineModel:
    return TimeSeriesBaselineModel(BaselineConfig(min_train_rows=50)).fit(_build_training_df())


# ---------------------------------------------------------------------------
# VersionEntry
# ---------------------------------------------------------------------------


class TestVersionEntry:
    def test_to_dict_includes_known_fields(self) -> None:
        entry = VersionEntry(
            version="v20260415_060000",
            trained_at="2026-04-15T06:00:00+00:00",
            artifact_dir="/tmp/v",
            train_rows=1000,
            lookback_days=30,
        )
        d = entry.to_dict()
        assert d["version"] == "v20260415_060000"
        assert d["train_rows"] == 1000
        assert d["lookback_days"] == 30

    def test_extra_metadata_round_trips(self) -> None:
        entry = VersionEntry(
            version="v1",
            trained_at="2026-01-01T00:00:00+00:00",
            artifact_dir="/tmp",
            extra={"git_sha": "abc123", "trigger": "manual"},
        )
        restored = VersionEntry.from_dict(entry.to_dict())
        assert restored.extra["git_sha"] == "abc123"
        assert restored.extra["trigger"] == "manual"

    def test_unknown_keys_become_extras(self) -> None:
        d = {
            "version": "v1",
            "trained_at": "2026-01-01T00:00:00+00:00",
            "artifact_dir": "/tmp",
            "weird_metric": 0.95,
        }
        entry = VersionEntry.from_dict(d)
        assert entry.extra == {"weird_metric": 0.95}

    def test_missing_optional_fields_default_to_zero(self) -> None:
        d = {
            "version": "v1",
            "trained_at": "2026-01-01T00:00:00+00:00",
            "artifact_dir": "/tmp",
        }
        entry = VersionEntry.from_dict(d)
        assert entry.train_rows == 0
        assert entry.lookback_days == 0


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_creates_versioned_subdir(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        entry = registry.register(_fitted_model(), train_rows=120, lookback_days=1)
        version_dir = tmp_path / entry.version
        assert version_dir.exists()
        assert (version_dir / "baseline_seasonal_profile.json").exists()

    def test_creates_latest_snapshot(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model())
        latest_dir = tmp_path / "latest"
        assert latest_dir.exists()
        assert (latest_dir / "baseline_seasonal_profile.json").exists()

    def test_writes_manifest_with_entry(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        entry = registry.register(_fitted_model(), train_rows=42, lookback_days=7)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["latest"] == entry.version
        assert len(manifest["versions"]) == 1
        assert manifest["versions"][0]["train_rows"] == 42
        assert manifest["versions"][0]["lookback_days"] == 7

    def test_register_appends_to_manifest(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model(), train_rows=10)
        registry.register(_fitted_model(), train_rows=20)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert len(manifest["versions"]) == 2

    def test_extra_metadata_persisted(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model(), git_sha="abc123")
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["versions"][0]["git_sha"] == "abc123"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_with_no_versions_raises(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            registry.load()

    def test_load_latest_returns_fitted_model(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model())
        loaded = registry.load()
        assert loaded.is_fitted is True

    def test_load_specific_version(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        entry = registry.register(_fitted_model())
        loaded = registry.load(entry.version)
        assert loaded.is_fitted is True

    def test_load_unknown_version_raises(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model())
        with pytest.raises(FileNotFoundError):
            registry.load("v00000000_000000")


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_list_versions_empty_when_unregistered(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        assert registry.list_versions() == []

    def test_list_versions_chronological(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        e1 = registry.register(_fitted_model())
        e2 = registry.register(_fitted_model())
        versions = [v.version for v in registry.list_versions()]
        assert versions == [e1.version, e2.version]

    def test_latest_version_tracks_most_recent(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        assert registry.latest_version() is None
        registry.register(_fitted_model())
        e2 = registry.register(_fitted_model())
        assert registry.latest_version() == e2.version


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------


class TestPrune:
    def test_keep_n_below_one_raises(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        with pytest.raises(ValueError, match="keep_n"):
            registry.prune(keep_n=0)

    def test_no_op_when_below_threshold(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        registry.register(_fitted_model())
        deleted = registry.prune(keep_n=5)
        assert deleted == []
        assert len(registry.list_versions()) == 1

    def test_deletes_oldest_first(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        # Manually register 3 versions with distinct timestamps so prune has
        # something deterministic to delete (the natural timestamp tag has
        # second resolution and three quick calls collide).
        for i in range(3):
            entry = registry.register(_fitted_model())
            # Mutate the manifest to give each entry a unique tag.
            manifest_path = tmp_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["versions"][-1]["version"] = f"v_test_{i:02d}"
            manifest["versions"][-1]["artifact_dir"] = str(tmp_path / f"v_test_{i:02d}")
            manifest["latest"] = f"v_test_{i:02d}"
            manifest_path.write_text(json.dumps(manifest))
            # Move the actual directory to match the renamed tag.
            (tmp_path / entry.version).rename(tmp_path / f"v_test_{i:02d}")

        deleted = registry.prune(keep_n=1)
        assert "v_test_00" in deleted
        assert "v_test_01" in deleted
        # Newest survives.
        assert [v.version for v in registry.list_versions()] == ["v_test_02"]
        # The latest/ snapshot directory must not be touched by prune.
        assert (tmp_path / "latest").exists()


# ---------------------------------------------------------------------------
# Manifest persistence
# ---------------------------------------------------------------------------


class TestManifestPersistence:
    def test_manifest_survives_new_registry_instance(self, tmp_path) -> None:
        first = ModelVersionRegistry(str(tmp_path))
        first.register(_fitted_model(), train_rows=99)

        # Fresh registry pointing at the same directory must see the entry.
        second = ModelVersionRegistry(str(tmp_path))
        versions = second.list_versions()
        assert len(versions) == 1
        assert versions[0].train_rows == 99

    def test_manifest_default_when_missing(self, tmp_path) -> None:
        registry = ModelVersionRegistry(str(tmp_path))
        # No file written yet — read should return the default empty manifest.
        assert registry.latest_version() is None
        assert registry.list_versions() == []
