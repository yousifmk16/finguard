"""
ML-01: Isolation Forest anomaly detector.

Trains an unsupervised sklearn IsolationForest on the feature matrix produced
by the FEA-01 pipeline (RollingWindowExtractor) and optionally extended by
FEA-02 (volatility), FEA-03 (growth rate), and FEA-04 (time context).

The model assigns an anomaly score to every incoming row.  Its output is
designed to feed directly into:
  - ENS-01  (weighted score fusion alongside TS-03 z-scores)
  - EXP-01  (explainability engine — feature contribution via SHAP, future)

Output columns produced by predict()
-------------------------------------
    if_score        float   Continuous anomaly score in [0, 1].  Higher values
                            indicate greater deviation from normal behaviour.
                            Derived from sklearn's score_samples() (negated and
                            min-max normalised using training-set statistics).
    if_anomaly      int8    Binary flag: 1 = anomaly, 0 = normal.  Based on
                            sklearn's built-in contamination threshold.

Algorithm notes
---------------
IsolationForest isolates anomalies by recursively partitioning the feature
space with random split hyperplanes.  Points that require fewer splits to
isolate score higher (more anomalous).  It is distribution-free, requires no
labels, and scales well to high-dimensional feature vectors — all desirable
properties for billing data where anomaly types are not known in advance.

Feature selection
-----------------
`IsolationForestConfig.feature_cols` controls which columns are fed into the
model.  The default list matches the FEA-01 rolling-window output for a
`total_cost` target with windows [5, 15, 60]:

    total_cost_roll5_mean   total_cost_roll5_std    ...  total_cost_roll5_zscore
    total_cost_roll15_mean  ...
    total_cost_roll60_mean  ...

plus FEA-04 time-context columns (hour_of_day, day_of_week).

If `feature_cols` is left empty, the detector falls back to all numeric
columns that are not in `exclude_cols`.

NaN handling
------------
Rolling features are NaN for the first (window − 1) rows of each series.
During `fit()` these rows are **dropped** from training.  During `predict()`
NaNs are **imputed** with the per-column median computed on the training set
so that inference never raises an error on short series.

Artifacts stored by save() / loaded by load()
----------------------------------------------
    <artifact_dir>/if_model.pkl      — joblib-serialised IsolationForest
    <artifact_dir>/if_config.json    — IsolationForestConfig as JSON
    <artifact_dir>/if_meta.json      — training metadata (feature list,
                                       medians, score normalisation params)

Integration with TS-05 versioning
----------------------------------
The registry in versioning.py currently manages TimeSeriesBaselineModel
artifacts.  IsolationForestDetector follows the same save/load contract so it
can be registered alongside or independently via a parallel registry or by
extending ModelVersionRegistry in a future sprint.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy sklearn import — keeps the module importable even without scikit-learn
# in environments that only need the config/metadata classes.
# ---------------------------------------------------------------------------

try:
    from sklearn.ensemble import IsolationForest as _SklearnIF
except ImportError as _err:  # pragma: no cover
    _SklearnIF = None  # type: ignore[assignment]
    _SKLEARN_MISSING_MSG = str(_err)
else:
    _SKLEARN_MISSING_MSG = ""

# File names written by save()
_MODEL_FILE = "if_model.pkl"
_CONFIG_FILE = "if_config.json"
_META_FILE = "if_meta.json"

# Columns that are never treated as features regardless of dtype
_DEFAULT_EXCLUDE_COLS = {
    "bucket",
    "account_id",
    "service",
    "region",
    # TS-01/02 forecast columns
    "forecast_mean",
    "forecast_std",
    # TS-03 residual columns
    "residual",
    "abs_residual",
    "z_score",
    "abs_z_score",
    # IF own output columns (avoid accidental self-referencing)
    "if_score",
    "if_anomaly",
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class IsolationForestConfig:
    """
    Hyper-parameters and feature settings for the Isolation Forest detector.

    Attributes
    ----------
    feature_cols:
        Explicit list of columns to use as the feature matrix.  When empty
        the detector auto-selects all numeric columns not in `exclude_cols`.
        Prefer explicit lists in production for reproducibility.
    exclude_cols:
        Columns to skip during auto-selection (only used when `feature_cols`
        is empty).  Extended automatically with _DEFAULT_EXCLUDE_COLS.
    n_estimators:
        Number of trees in the forest (sklearn default: 100).  Higher values
        give more stable scores at the cost of memory and fit time.
    contamination:
        Expected proportion of anomalies in the training set.  Controls the
        decision threshold used for `if_anomaly`.  "auto" delegates to
        sklearn (uses 0.1 internally).  For production, set this based on
        empirically observed anomaly rate.
    max_samples:
        Sub-sampling size passed to IsolationForest.  "auto" uses
        min(256, n_samples).  A fixed integer (e.g. 512) trades variance for
        determinism.
    random_state:
        Seed for reproducible training runs.
    group_cols:
        Columns that identify independent billing series.  Used by
        `fit_group` / `predict_group` to keep per-series context; the model
        itself is trained on pooled data across all groups.
    artifact_dir:
        Default directory for save() / load().
    min_train_rows:
        Minimum non-NaN rows required after dropping NaN feature rows.
        Raises ValueError during fit if the cleaned training set is smaller.
    """

    feature_cols: List[str] = field(default_factory=list)
    exclude_cols: List[str] = field(default_factory=list)
    n_estimators: int = 100
    contamination: float | str = "auto"
    max_samples: int | str = "auto"
    random_state: int = 42
    group_cols: List[str] = field(
        default_factory=lambda: ["account_id", "service", "region"]
    )
    artifact_dir: str = "ml/artifacts"
    min_train_rows: int = 60


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class IsolationForestDetector:
    """
    Unsupervised anomaly detector based on sklearn IsolationForest (ML-01).

    Usage — training
    ----------------
    from ml.src.models.isolation_forest import IsolationForestDetector, IsolationForestConfig

    detector = IsolationForestDetector(IsolationForestConfig())
    detector.fit(df_features)           # single / pooled series
    detector.fit_group(df_features)     # same; groups are pooled for training

    Usage — inference
    -----------------
    scored_df = detector.predict(df_features)
    # scored_df gains two columns:
    #   if_score   – float in [0, 1], higher = more anomalous
    #   if_anomaly – int8  1 = anomaly, 0 = normal

    Usage — group inference
    -----------------------
    scored_df = detector.predict_group(df_features)
    # Scores each (account_id, service, region) group independently to
    # preserve per-series context, then reassembles into the original index.

    Usage — persistence
    -------------------
    detector.save("ml/artifacts")
    detector2 = IsolationForestDetector.load("ml/artifacts")
    """

    def __init__(self, config: IsolationForestConfig | None = None) -> None:
        self.config = config or IsolationForestConfig()
        self._model: Optional[object] = None  # sklearn IsolationForest
        self._feature_cols: List[str] = []    # resolved at fit time
        self._medians: Dict[str, float] = {}  # for NaN imputation at predict
        # Min-max normalisation params derived from training score_samples()
        self._score_min: float = 0.0
        self._score_max: float = 1.0
        self._fitted: bool = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> "IsolationForestDetector":
        """
        Train the Isolation Forest on a (possibly multi-series) DataFrame.

        Parameters
        ----------
        df:
            Feature DataFrame produced by RollingWindowExtractor (FEA-01)
            and optionally extended by FEA-02 / FEA-03 / FEA-04.  Rows with
            NaN in any selected feature column are dropped before fitting.

        Returns
        -------
        self (for chaining)
        """
        self._check_sklearn()
        X, feature_cols = self._prepare_train(df)
        self._feature_cols = feature_cols

        model = _SklearnIF(
            n_estimators=self.config.n_estimators,
            contamination=self.config.contamination,
            max_samples=self.config.max_samples,
            random_state=self.config.random_state,
            n_jobs=-1,
        )
        model.fit(X)
        self._model = model

        # Compute score normalisation params on training data
        raw_scores = model.score_samples(X)
        self._score_min = float(raw_scores.min())
        self._score_max = float(raw_scores.max())

        self._fitted = True
        logger.info(
            "IsolationForest fitted: %d rows, %d features, "
            "score range [%.4f, %.4f]",
            len(X),
            len(feature_cols),
            self._score_min,
            self._score_max,
        )
        return self

    def fit_group(self, df: pd.DataFrame) -> "IsolationForestDetector":
        """
        Train on a multi-series DataFrame.  All groups are pooled into a
        single training set so the model learns a shared normality profile
        across accounts, services, and regions.

        This is the recommended training method when data from multiple
        billing dimensions is available in the lookback window.
        """
        return self.fit(df)

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score every row in `df` and append `if_score` and `if_anomaly`.

        Parameters
        ----------
        df:
            Feature DataFrame with at least the columns present during fit.
            Missing feature columns are imputed with their training-set median.

        Returns
        -------
        Copy of `df` with two additional columns:
            if_score   float64  Normalised anomaly score in [0, 1].
            if_anomaly int8     1 if the row is classified as anomalous, else 0.
        """
        self._check_fitted()
        X = self._prepare_predict(df)

        raw_scores = self._model.score_samples(X)
        if_preds = self._model.predict(X)  # 1 = normal, -1 = anomaly

        if_score = self._normalise_scores(raw_scores)
        if_anomaly = (if_preds == -1).astype("int8")

        result = df.copy()
        result["if_score"] = if_score
        result["if_anomaly"] = if_anomaly
        return result

    def predict_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score a multi-series DataFrame, processing each group independently
        to preserve per-series row ordering.  The model is shared across all
        groups (no per-group model fitting here — that is a future extension).

        Returns
        -------
        Copy of `df` with `if_score` and `if_anomaly` columns, preserving
        the original index order.
        """
        self._check_fitted()
        group_keys = [k for k in self.config.group_cols if k in df.columns]

        if not group_keys:
            return self.predict(df)

        results: list[pd.DataFrame] = []
        for _, group in df.groupby(group_keys, sort=False):
            scored = self.predict(group)
            results.append(scored)

        return pd.concat(results).reindex(df.index)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, artifact_dir: str | None = None) -> Path:
        """
        Persist the fitted detector to disk.

        Files written
        -------------
        <artifact_dir>/if_model.pkl    — joblib-serialised IsolationForest
        <artifact_dir>/if_config.json  — IsolationForestConfig as JSON
        <artifact_dir>/if_meta.json    — feature list, medians, score norms

        Returns
        -------
        Path to the artifact directory.
        """
        self._check_fitted()
        import joblib  # bundled with scikit-learn  # noqa: PLC0415

        out_dir = Path(artifact_dir or self.config.artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. Model binary
        joblib.dump(self._model, out_dir / _MODEL_FILE)

        # 2. Config
        cfg_dict = asdict(self.config)
        with (out_dir / _CONFIG_FILE).open("w") as f:
            json.dump(cfg_dict, f, indent=2)

        # 3. Training metadata needed for predict()
        meta = {
            "feature_cols": self._feature_cols,
            "medians": self._medians,
            "score_min": self._score_min,
            "score_max": self._score_max,
        }
        with (out_dir / _META_FILE).open("w") as f:
            json.dump(meta, f, indent=2)

        logger.info("IsolationForestDetector saved to %s", out_dir)
        return out_dir

    @classmethod
    def load(cls, artifact_dir: str) -> "IsolationForestDetector":
        """
        Restore a previously saved detector.

        Parameters
        ----------
        artifact_dir:
            Directory containing if_model.pkl, if_config.json, if_meta.json.
        """
        cls._check_sklearn_cls()
        import joblib  # noqa: PLC0415

        in_dir = Path(artifact_dir)
        model_path = in_dir / _MODEL_FILE
        config_path = in_dir / _CONFIG_FILE
        meta_path = in_dir / _META_FILE

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model artifact not found at {model_path}. "
                "Run IsolationForestDetector.fit() and .save() first."
            )

        sklearn_model = joblib.load(model_path)

        config = IsolationForestConfig()
        if config_path.exists():
            with config_path.open() as f:
                raw = json.load(f)
                config = IsolationForestConfig(**raw)

        detector = cls(config)
        detector._model = sklearn_model

        if meta_path.exists():
            with meta_path.open() as f:
                meta = json.load(f)
            detector._feature_cols = meta.get("feature_cols", [])
            detector._medians = meta.get("medians", {})
            detector._score_min = meta.get("score_min", 0.0)
            detector._score_max = meta.get("score_max", 1.0)

        detector._fitted = True
        logger.info("IsolationForestDetector loaded from %s", in_dir)
        return detector

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def feature_cols(self) -> List[str]:
        """The resolved feature column list (available after fit)."""
        return list(self._feature_cols)

    # ------------------------------------------------------------------
    # Internal: feature matrix preparation
    # ------------------------------------------------------------------

    def _resolve_feature_cols(self, df: pd.DataFrame) -> List[str]:
        """
        Determine which columns to use as the feature matrix.

        Priority:
        1. Explicit list in config.feature_cols.
        2. All numeric columns not in exclude_cols / _DEFAULT_EXCLUDE_COLS.
        """
        if self.config.feature_cols:
            missing = [c for c in self.config.feature_cols if c not in df.columns]
            if missing:
                warnings.warn(
                    f"Configured feature_cols not found in DataFrame: {missing}. "
                    "They will be dropped from the feature set.",
                    stacklevel=4,
                )
            return [c for c in self.config.feature_cols if c in df.columns]

        # Auto-select: numeric columns only, excluding known non-feature cols
        user_exclude = set(self.config.exclude_cols)
        all_exclude = _DEFAULT_EXCLUDE_COLS | user_exclude

        # Also exclude binary CI-breach / is_outside_* columns
        auto_exclude_patterns = ("is_outside_ci_", "ci_lower_", "ci_upper_")

        cols = []
        for col in df.select_dtypes(include=[np.number]).columns:
            if col in all_exclude:
                continue
            if any(col.startswith(p) for p in auto_exclude_patterns):
                continue
            cols.append(col)

        if not cols:
            raise ValueError(
                "No numeric feature columns found in DataFrame. "
                "Run RollingWindowExtractor (FEA-01) first, or set "
                "IsolationForestConfig.feature_cols explicitly."
            )
        return cols

    def _prepare_train(self, df: pd.DataFrame) -> tuple[np.ndarray, List[str]]:
        """
        Resolve features, compute medians, drop NaN rows, validate size.

        Returns (X_clean, feature_cols)
        """
        if df.empty:
            raise ValueError("Training DataFrame is empty.")

        feature_cols = self._resolve_feature_cols(df)
        X = df[feature_cols].astype(float)

        # Store per-column medians for predict-time imputation
        self._medians = {
            col: float(X[col].median()) for col in feature_cols
        }

        # Drop rows where any feature is NaN
        nan_mask = X.isna().any(axis=1)
        n_dropped = int(nan_mask.sum())
        if n_dropped:
            logger.debug(
                "Dropped %d rows with NaN features from training set "
                "(%d remain).",
                n_dropped,
                len(X) - n_dropped,
            )
        X_clean = X[~nan_mask].to_numpy()

        if len(X_clean) < self.config.min_train_rows:
            raise ValueError(
                f"Training set has only {len(X_clean)} non-NaN rows after "
                f"feature selection (need >= {self.config.min_train_rows}). "
                "Increase lookback_days or reduce min_train_rows."
            )

        return X_clean, feature_cols

    def _prepare_predict(self, df: pd.DataFrame) -> np.ndarray:
        """
        Build the inference feature matrix: select columns, impute NaNs.
        """
        missing_cols = [c for c in self._feature_cols if c not in df.columns]
        if missing_cols:
            warnings.warn(
                f"Feature columns missing at inference time: {missing_cols}. "
                "Imputing with training-set median.",
                stacklevel=3,
            )

        X = pd.DataFrame(index=df.index)
        for col in self._feature_cols:
            if col in df.columns:
                X[col] = df[col].astype(float)
            else:
                X[col] = self._medians.get(col, 0.0)

        # Impute remaining NaNs with training medians
        for col in self._feature_cols:
            if X[col].isna().any():
                fill = self._medians.get(col, 0.0)
                X[col] = X[col].fillna(fill)

        return X.to_numpy()

    # ------------------------------------------------------------------
    # Internal: score normalisation
    # ------------------------------------------------------------------

    def _normalise_scores(self, raw_scores: np.ndarray) -> np.ndarray:
        """
        Map sklearn's score_samples() output to [0, 1] where 1 = most
        anomalous.

        sklearn returns values in roughly (-0.5, 0.5) where lower = more
        anomalous.  We negate and min-max scale using training-set extremes
        so the output is comparable across retrains.

        Clipped to [0, 1] to handle scores that fall outside the training
        range (possible for extreme novel anomalies).
        """
        negated = -raw_scores
        denom = (-self._score_min) - (-self._score_max)
        if denom == 0.0:
            # Degenerate: all training scores identical — return 0.5 uniform
            return np.full_like(negated, 0.5, dtype=float)

        norm = (negated - (-self._score_max)) / denom
        return np.clip(norm, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Internal: guards
    # ------------------------------------------------------------------

    @staticmethod
    def _check_sklearn() -> None:
        if _SklearnIF is None:  # pragma: no cover
            raise ImportError(
                "scikit-learn is required for IsolationForestDetector. "
                f"Install it with: pip install scikit-learn\n"
                f"Original error: {_SKLEARN_MISSING_MSG}"
            )

    @classmethod
    def _check_sklearn_cls(cls) -> None:
        cls._check_sklearn()

    def _check_fitted(self) -> None:
        if not self._fitted or self._model is None:
            raise RuntimeError(
                "Detector is not fitted. Call fit() or fit_group() first, "
                "or load a saved detector with IsolationForestDetector.load()."
            )
