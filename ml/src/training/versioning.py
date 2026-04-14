"""
TS-05: Model artifact versioning for the time-series baseline model.

Every call to ModelVersionRegistry.register() saves the fitted model into a
timestamped subdirectory under ``registry_dir``, records metadata in a
``manifest.json`` index, and updates a ``latest/`` snapshot directory so
the inference path always has a stable load target.

Directory layout
----------------
<registry_dir>/
├── manifest.json               ← version index (JSON)
├── latest/                     ← copy of the most-recently registered version
│   ├── baseline_config.json
│   └── baseline_seasonal_profile.json
├── v20260414_142300/
│   ├── baseline_config.json
│   └── baseline_seasonal_profile.json
└── v20260415_060000/
    ├── baseline_config.json
    └── baseline_seasonal_profile.json

manifest.json schema
--------------------
{
  "latest": "v20260415_060000",
  "versions": [
    {
      "version":    "v20260415_060000",
      "trained_at": "2026-04-15T06:00:00+00:00",
      "artifact_dir": "<registry_dir>/v20260415_060000",
      "train_rows": 43200,
      "lookback_days": 30
    },
    ...
  ]
}

Versions are ordered oldest-first in the manifest.  ``latest`` always
names the last entry.

Integration with TS-04 (RetrainJob)
------------------------------------
Pass the registry's ``register`` method as the ``on_success`` callback
in ``RetrainConfig``, or use the helper ``make_retrain_config``:

    registry = ModelVersionRegistry("ml/artifacts")
    config   = registry.make_retrain_config(db_url=..., interval_hours=24)
    scheduler = RetrainScheduler(config)
    scheduler.start()

The inference path loads the latest model once at startup:

    model = ModelVersionRegistry("ml/artifacts").load()
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ml.src.models.baseline import TimeSeriesBaselineModel

logger = logging.getLogger(__name__)

# File names written by TimeSeriesBaselineModel.save()
_PROFILE_FILE = "baseline_seasonal_profile.json"
_CONFIG_FILE = "baseline_config.json"
_MANIFEST_FILE = "manifest.json"
_LATEST_DIR = "latest"


# ---------------------------------------------------------------------------
# Version entry (one record per registered model)
# ---------------------------------------------------------------------------


@dataclass
class VersionEntry:
    """
    Metadata record stored in manifest.json for one trained artifact.

    Attributes
    ----------
    version:
        Unique version identifier, e.g. ``v20260415_060000``.
    trained_at:
        ISO-8601 UTC timestamp when the model was registered.
    artifact_dir:
        Absolute path to the versioned subdirectory.
    train_rows:
        Number of rows used for this training run (0 if unknown).
    lookback_days:
        Training lookback window used (0 if unknown).
    extra:
        Arbitrary key-value pairs for future metadata fields.
    """

    version: str
    trained_at: str
    artifact_dir: str
    train_rows: int = 0
    lookback_days: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "version": self.version,
            "trained_at": self.trained_at,
            "artifact_dir": self.artifact_dir,
            "train_rows": self.train_rows,
            "lookback_days": self.lookback_days,
        }
        d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VersionEntry":
        known = {"version", "trained_at", "artifact_dir", "train_rows", "lookback_days"}
        extra = {k: v for k, v in d.items() if k not in known}
        return cls(
            version=d["version"],
            trained_at=d["trained_at"],
            artifact_dir=d["artifact_dir"],
            train_rows=d.get("train_rows", 0),
            lookback_days=d.get("lookback_days", 0),
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ModelVersionRegistry:
    """
    Manages versioned artifacts for TimeSeriesBaselineModel.

    Usage — registering a new model after retrain
    ----------------------------------------------
    registry = ModelVersionRegistry("ml/artifacts")
    registry.register(model, train_rows=43200, lookback_days=30)

    Usage — loading the latest model at inference startup
    ------------------------------------------------------
    model = ModelVersionRegistry("ml/artifacts").load()

    Usage — loading a specific historical version
    ----------------------------------------------
    model = ModelVersionRegistry("ml/artifacts").load("v20260414_142300")

    Usage — housekeeping
    --------------------
    registry.prune(keep_n=5)          # delete all but the 5 most recent
    entries = registry.list_versions() # returns List[VersionEntry]
    """

    def __init__(self, registry_dir: str = "ml/artifacts") -> None:
        self._root = Path(registry_dir)

    # ------------------------------------------------------------------
    # Register
    # ------------------------------------------------------------------

    def register(
        self,
        model: TimeSeriesBaselineModel,
        train_rows: int = 0,
        lookback_days: int = 0,
        **extra: Any,
    ) -> VersionEntry:
        """
        Save a freshly fitted model as a new versioned artifact.

        Steps
        -----
        1. Generate a timestamp-based version tag.
        2. Save model files to ``<registry_dir>/<version>/``.
        3. Copy files to ``<registry_dir>/latest/``.
        4. Append a VersionEntry to manifest.json.

        Parameters
        ----------
        model:
            A fitted TimeSeriesBaselineModel instance.
        train_rows:
            Row count used for this training run (stored in manifest).
        lookback_days:
            Lookback window used (stored in manifest).
        **extra:
            Any additional metadata to record in the manifest entry.

        Returns
        -------
        The VersionEntry that was appended to the manifest.
        """
        self._root.mkdir(parents=True, exist_ok=True)

        version = self._make_version_tag()
        version_dir = self._root / version

        # Save model files into the versioned subdirectory
        model.save(str(version_dir))

        # Refresh latest/ snapshot
        self._update_latest(version_dir)

        # Record in manifest
        entry = VersionEntry(
            version=version,
            trained_at=datetime.now(tz=timezone.utc).isoformat(),
            artifact_dir=str(version_dir.resolve()),
            train_rows=train_rows,
            lookback_days=lookback_days,
            extra=extra,
        )
        manifest = self._read_manifest()
        manifest["versions"].append(entry.to_dict())
        manifest["latest"] = version
        self._write_manifest(manifest)

        logger.info(
            "Registered model version %s (%d rows) at %s",
            version,
            train_rows,
            version_dir,
        )
        return entry

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, version: Optional[str] = None) -> TimeSeriesBaselineModel:
        """
        Restore a model from a versioned artifact directory.

        Parameters
        ----------
        version:
            Version tag to load (e.g. ``"v20260415_060000"``).
            Pass ``None`` (default) to load the latest registered version.

        Raises
        ------
        FileNotFoundError  if no versions have been registered yet, or if
                           the requested version does not exist.
        """
        if version is None:
            load_dir = self._root / _LATEST_DIR
            if not load_dir.exists():
                raise FileNotFoundError(
                    f"No 'latest' artifact found in {self._root}. "
                    "Run ModelVersionRegistry.register() first."
                )
        else:
            load_dir = self._root / version
            if not load_dir.exists():
                raise FileNotFoundError(
                    f"Version '{version}' not found at {load_dir}. "
                    f"Available: {[e.version for e in self.list_versions()]}"
                )

        logger.info("Loading model from %s", load_dir)
        return TimeSeriesBaselineModel.load(str(load_dir))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_versions(self) -> List[VersionEntry]:
        """
        Return all registered versions in chronological order (oldest first).
        """
        manifest = self._read_manifest()
        return [VersionEntry.from_dict(d) for d in manifest["versions"]]

    def latest_version(self) -> Optional[str]:
        """Return the version tag of the most recently registered model."""
        manifest = self._read_manifest()
        return manifest.get("latest")

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def prune(self, keep_n: int = 5) -> List[str]:
        """
        Delete old versioned artifact directories, keeping the ``keep_n``
        most recent.  The ``latest/`` directory is never deleted.

        Parameters
        ----------
        keep_n:
            Number of most-recent versions to retain.

        Returns
        -------
        List of version tags that were deleted.
        """
        if keep_n < 1:
            raise ValueError("keep_n must be >= 1.")

        manifest = self._read_manifest()
        all_versions: List[dict] = manifest.get("versions", [])

        if len(all_versions) <= keep_n:
            logger.info(
                "Prune: %d versions present, keep_n=%d — nothing to delete.",
                len(all_versions),
                keep_n,
            )
            return []

        to_delete = all_versions[: len(all_versions) - keep_n]
        to_keep = all_versions[len(all_versions) - keep_n :]

        deleted: List[str] = []
        for entry_dict in to_delete:
            tag = entry_dict["version"]
            version_dir = self._root / tag
            if version_dir.exists():
                shutil.rmtree(version_dir)
                logger.info("Pruned version %s", tag)
            deleted.append(tag)

        manifest["versions"] = to_keep
        self._write_manifest(manifest)
        return deleted

    # ------------------------------------------------------------------
    # TS-04 integration helper
    # ------------------------------------------------------------------

    def make_retrain_config(self, **kwargs: Any) -> "RetrainConfig":  # noqa: F821
        """
        Build a RetrainConfig whose on_success callback automatically
        registers each newly trained model with this registry.

        All keyword arguments are forwarded to RetrainConfig.

        Example
        -------
        registry = ModelVersionRegistry("ml/artifacts")
        config   = registry.make_retrain_config(
            db_url=os.environ["DATABASE_URL"],
            interval_hours=24,
            lookback_days=30,
        )
        RetrainScheduler(config).start()
        """
        from ml.src.training.retrain import RetrainConfig  # noqa: PLC0415

        lookback = kwargs.get("lookback_days", 30)

        def _on_success(model: TimeSeriesBaselineModel) -> None:
            self.register(model, lookback_days=lookback)

        kwargs.setdefault("artifact_dir", str(self._root / _LATEST_DIR))
        kwargs["on_success"] = _on_success
        return RetrainConfig(**kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_version_tag() -> str:
        """Generate a sortable timestamp-based version tag."""
        return datetime.now(tz=timezone.utc).strftime("v%Y%m%d_%H%M%S")

    def _manifest_path(self) -> Path:
        return self._root / _MANIFEST_FILE

    def _read_manifest(self) -> dict:
        path = self._manifest_path()
        if not path.exists():
            return {"latest": None, "versions": []}
        with path.open() as f:
            return json.load(f)

    def _write_manifest(self, manifest: dict) -> None:
        with self._manifest_path().open("w") as f:
            json.dump(manifest, f, indent=2)

    def _update_latest(self, version_dir: Path) -> None:
        """
        Overwrite ``<registry_dir>/latest/`` with copies of the versioned
        files.  Uses file copies rather than symlinks for cross-platform
        compatibility (Windows does not always allow unprivileged symlinks).
        """
        latest_dir = self._root / _LATEST_DIR
        if latest_dir.exists():
            shutil.rmtree(latest_dir)
        latest_dir.mkdir(parents=True)

        for fname in (_PROFILE_FILE, _CONFIG_FILE):
            src = version_dir / fname
            if src.exists():
                shutil.copy2(src, latest_dir / fname)
