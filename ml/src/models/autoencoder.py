"""
ML-01b: Autoencoder anomaly detector.

Replaces IsolationForestDetector as the second ensemble signal in ENS-01.
Anomalies are identified by high reconstruction error: the model learns to
compress and reconstruct normal billing patterns; unusual rows that deviate
from learnt normality produce larger errors and therefore score higher.

Architecture
------------
Shallow feed-forward autoencoder implemented via scikit-learn's MLPRegressor
trained in identity mode (input = target = features):

    input  →  hidden (bottleneck)  →  output
    dim_in →  hidden_dim           →  dim_in

Default hidden_dim = max(2, dim_in // 3), giving roughly 33 % compression
which is enough to force the encoder to discard noise while retaining
dominant cost-pattern structure.

Anomaly scoring
---------------
Reconstruction MSE per row is computed post-fit and normalised to [0, 1]
using training-set percentiles:

    raw_error  = mean_squared_error(row, reconstructed_row)
    ae_score   = clip((raw_error - p_lo) / (p_hi - p_lo), 0, 1)

where p_lo and p_hi are the 5th and 95th percentile reconstruction errors
on the training set, making the score robust to occasional extreme outliers.

Output columns (identical names to IsolationForestDetector for scorer compatibility)
-------------------------------------------------------------------------------------
    if_score     float64   Normalised reconstruction error in [0, 1].
    if_anomaly   int8      1 if if_score ≥ ae_threshold, else 0.

Artifacts stored by save() / loaded by load()
----------------------------------------------
    <artifact_dir>/ae_model.pkl     — joblib-serialised MLPRegressor
    <artifact_dir>/ae_config.json  — AutoencoderConfig as JSON
    <artifact_dir>/ae_meta.json    — feature list, scaler params, error norms
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

try:
    from sklearn.neural_network import MLPRegressor as _MLPRegressor
    from sklearn.preprocessing import StandardScaler as _StandardScaler
except ImportError as _err:  # pragma: no cover
    _MLPRegressor = None  # type: ignore[assignment,misc]
    _StandardScaler = None  # type: ignore[assignment,misc]
    _SKLEARN_MISSING_MSG = str(_err)
else:
    _SKLEARN_MISSING_MSG = ""

_MODEL_FILE = "ae_model.pkl"
_SCALER_FILE = "ae_scaler.pkl"
_CONFIG_FILE = "ae_config.json"
_META_FILE = "ae_meta.json"

_DEFAULT_EXCLUDE_COLS = {
    "bucket", "account_id", "service", "region",
    "forecast_mean", "forecast_std",
    "residual", "abs_residual", "z_score", "abs_z_score",
    "if_score", "if_anomaly",
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AutoencoderConfig:
    """
    Hyper-parameters for the autoencoder anomaly detector.

    Attributes
    ----------
    feature_cols:
        Explicit list of columns to use. When empty, all numeric columns
        not in ``exclude_cols`` are selected automatically.
    exclude_cols:
        Columns to skip during auto-selection.
    hidden_dim:
        Bottleneck layer size. 0 = auto (max(2, n_features // 3)).
    max_iter:
        Maximum training iterations for MLPRegressor.
    random_state:
        Seed for reproducibility.
    ae_threshold:
        Normalised reconstruction error above which a row is flagged as
        anomalous (``if_anomaly = 1``).  Range [0, 1]; default 0.6.
    error_pct_lo / error_pct_hi:
        Percentiles used to normalise raw MSE to [0, 1].  Rows with
        error below p_lo score 0; rows above p_hi score 1.
    group_cols:
        Columns identifying independent billing series (used by fit_group).
    artifact_dir:
        Default directory for save() / load().
    min_train_rows:
        Minimum non-NaN rows required before fitting.
    """

    feature_cols: List[str] = field(default_factory=list)
    exclude_cols: List[str] = field(default_factory=list)
    hidden_dim: int = 0           # 0 = auto
    max_iter: int = 200
    random_state: int = 42
    ae_threshold: float = 0.6
    error_pct_lo: float = 5.0
    error_pct_hi: float = 95.0
    group_cols: List[str] = field(
        default_factory=lambda: ["account_id", "service", "region"]
    )
    artifact_dir: str = "ml/artifacts"
    min_train_rows: int = 60


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class AutoencoderDetector:
    """
    Autoencoder anomaly detector with the same fit/predict/save/load interface
    as IsolationForestDetector (ML-01) so it is a drop-in replacement in the
    OnlineScorer ensemble.

    Usage — training
    ----------------
    detector = AutoencoderDetector(AutoencoderConfig())
    detector.fit(df_features)

    Usage — inference
    -----------------
    scored_df = detector.predict(df_features)
    # scored_df gains:
    #   if_score   – float in [0, 1], higher = more anomalous (recon error)
    #   if_anomaly – int8  1 = anomaly, 0 = normal

    Usage — persistence
    -------------------
    detector.save("ml/artifacts")
    detector2 = AutoencoderDetector.load("ml/artifacts")
    """

    def __init__(self, config: AutoencoderConfig | None = None) -> None:
        self.config = config or AutoencoderConfig()
        self._model: Optional[object] = None       # MLPRegressor
        self._scaler: Optional[object] = None      # StandardScaler
        self._feature_cols: List[str] = []
        self._error_lo: float = 0.0
        self._error_hi: float = 1.0
        self._fitted: bool = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> "AutoencoderDetector":
        """
        Train the autoencoder on a (possibly multi-series) DataFrame.

        Rows with NaN in any selected feature column are dropped before
        fitting.  Features are z-score scaled (zero mean, unit variance)
        before being fed to the MLP so that cost columns with different
        magnitudes do not dominate the reconstruction loss.

        Returns self for chaining.
        """
        self._check_sklearn()
        X, feature_cols = self._prepare_train(df)
        self._feature_cols = feature_cols

        hidden_dim = self.config.hidden_dim or max(2, len(feature_cols) // 3)

        model = _MLPRegressor(
            hidden_layer_sizes=(hidden_dim,),
            activation="relu",
            max_iter=self.config.max_iter,
            random_state=self.config.random_state,
            n_iter_no_change=20,
            tol=1e-4,
        )
        # Train to reconstruct its own input (identity mapping through bottleneck)
        model.fit(X, X)
        self._model = model

        # Compute per-row reconstruction MSE on training data for normalisation
        X_hat = model.predict(X)
        train_errors = np.mean((X - X_hat) ** 2, axis=1)
        self._error_lo = float(np.percentile(train_errors, self.config.error_pct_lo))
        self._error_hi = float(np.percentile(train_errors, self.config.error_pct_hi))
        # Guard against degenerate case where all errors are identical
        if self._error_hi <= self._error_lo:
            self._error_hi = self._error_lo + 1e-9

        self._fitted = True
        logger.info(
            "AutoencoderDetector fitted: %d rows, %d features, "
            "hidden_dim=%d, error range [%.6f, %.6f]",
            len(X), len(feature_cols), hidden_dim,
            self._error_lo, self._error_hi,
        )
        return self

    def fit_group(self, df: pd.DataFrame) -> "AutoencoderDetector":
        """
        Train on a multi-series DataFrame — all groups are pooled so the
        model learns a shared normality profile (same as IF's fit_group).
        """
        return self.fit(df)

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score every row and append ``if_score`` and ``if_anomaly``.

        Parameters
        ----------
        df:
            Feature DataFrame. Missing feature columns are imputed with 0
            (post-scaling) so inference never errors on short series.

        Returns
        -------
        Copy of ``df`` with two extra columns:
            if_score   float64  Normalised reconstruction error in [0, 1].
            if_anomaly int8     1 if if_score ≥ ae_threshold.
        """
        self._check_fitted()
        X = self._prepare_predict(df)

        X_hat = self._model.predict(X)  # type: ignore[union-attr]
        raw_errors = np.mean((X - X_hat) ** 2, axis=1)

        denom = self._error_hi - self._error_lo
        if_score = np.clip(
            (raw_errors - self._error_lo) / denom, 0.0, 1.0
        )
        if_anomaly = (if_score >= self.config.ae_threshold).astype("int8")

        result = df.copy()
        result["if_score"] = if_score
        result["if_anomaly"] = if_anomaly
        return result

    def predict_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score a multi-series DataFrame, processing each group independently.
        """
        self._check_fitted()
        group_keys = [k for k in self.config.group_cols if k in df.columns]
        if not group_keys:
            return self.predict(df)

        results: list[pd.DataFrame] = []
        for _, group in df.groupby(group_keys, sort=False):
            results.append(self.predict(group))
        return pd.concat(results).reindex(df.index)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, artifact_dir: str | None = None) -> Path:
        """
        Persist the fitted detector to disk.

        Files written
        -------------
        <artifact_dir>/ae_model.pkl    — joblib-serialised MLPRegressor
        <artifact_dir>/ae_scaler.pkl   — joblib-serialised StandardScaler
        <artifact_dir>/ae_config.json  — AutoencoderConfig as JSON
        <artifact_dir>/ae_meta.json    — feature list + error normalisation params

        Returns the artifact directory Path.
        """
        self._check_fitted()
        import joblib  # noqa: PLC0415

        out_dir = Path(artifact_dir or self.config.artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        joblib.dump(self._model, out_dir / _MODEL_FILE)
        joblib.dump(self._scaler, out_dir / _SCALER_FILE)

        with (out_dir / _CONFIG_FILE).open("w") as f:
            json.dump(asdict(self.config), f, indent=2)

        meta = {
            "feature_cols": self._feature_cols,
            "error_lo": self._error_lo,
            "error_hi": self._error_hi,
        }
        with (out_dir / _META_FILE).open("w") as f:
            json.dump(meta, f, indent=2)

        logger.info("AutoencoderDetector saved to %s", out_dir)
        return out_dir

    @classmethod
    def load(cls, artifact_dir: str) -> "AutoencoderDetector":
        """
        Restore a previously saved detector.

        Raises FileNotFoundError if ae_model.pkl is missing.
        """
        cls._check_sklearn_cls()
        import joblib  # noqa: PLC0415

        in_dir = Path(artifact_dir)
        model_path = in_dir / _MODEL_FILE

        if not model_path.exists():
            raise FileNotFoundError(
                f"Autoencoder model artifact not found at {model_path}. "
                "Run AutoencoderDetector.fit() and .save() first."
            )

        config = AutoencoderConfig()
        config_path = in_dir / _CONFIG_FILE
        if config_path.exists():
            with config_path.open() as f:
                config = AutoencoderConfig(**json.load(f))

        detector = cls(config)
        detector._model = joblib.load(model_path)

        scaler_path = in_dir / _SCALER_FILE
        if scaler_path.exists():
            detector._scaler = joblib.load(scaler_path)

        meta_path = in_dir / _META_FILE
        if meta_path.exists():
            with meta_path.open() as f:
                meta = json.load(f)
            detector._feature_cols = meta.get("feature_cols", [])
            detector._error_lo = meta.get("error_lo", 0.0)
            detector._error_hi = meta.get("error_hi", 1.0)

        detector._fitted = True
        logger.info("AutoencoderDetector loaded from %s", in_dir)
        return detector

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def feature_cols(self) -> List[str]:
        return list(self._feature_cols)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_feature_cols(self, df: pd.DataFrame) -> List[str]:
        if self.config.feature_cols:
            missing = [c for c in self.config.feature_cols if c not in df.columns]
            if missing:
                warnings.warn(
                    f"Configured feature_cols not found in DataFrame: {missing}. "
                    "They will be dropped from the feature set.",
                    stacklevel=4,
                )
            return [c for c in self.config.feature_cols if c in df.columns]

        user_exclude = set(self.config.exclude_cols)
        all_exclude = _DEFAULT_EXCLUDE_COLS | user_exclude
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
                "AutoencoderConfig.feature_cols explicitly."
            )
        return cols

    def _prepare_train(self, df: pd.DataFrame) -> tuple[np.ndarray, List[str]]:
        if df.empty:
            raise ValueError("Training DataFrame is empty.")

        feature_cols = self._resolve_feature_cols(df)
        X_raw = df[feature_cols].astype(float)

        nan_mask = X_raw.isna().any(axis=1)
        n_dropped = int(nan_mask.sum())
        if n_dropped:
            logger.debug("Dropped %d NaN rows from training (%d remain).", n_dropped, len(X_raw) - n_dropped)
        X_clean = X_raw[~nan_mask].to_numpy()

        if len(X_clean) < self.config.min_train_rows:
            raise ValueError(
                f"Training set has only {len(X_clean)} non-NaN rows "
                f"(need >= {self.config.min_train_rows})."
            )

        # Fit and apply StandardScaler (zero mean, unit variance)
        scaler = _StandardScaler()
        X_scaled = scaler.fit_transform(X_clean)
        self._scaler = scaler

        return X_scaled, feature_cols

    def _prepare_predict(self, df: pd.DataFrame) -> np.ndarray:
        X = pd.DataFrame(index=df.index)
        for col in self._feature_cols:
            if col in df.columns:
                X[col] = df[col].astype(float)
            else:
                X[col] = 0.0

        # Impute remaining NaNs with column median
        for col in self._feature_cols:
            if X[col].isna().any():
                X[col] = X[col].fillna(X[col].median())

        X_np = X.to_numpy()

        if self._scaler is not None:
            X_np = self._scaler.transform(X_np)  # type: ignore[union-attr]

        return X_np

    @staticmethod
    def _check_sklearn() -> None:
        if _MLPRegressor is None:  # pragma: no cover
            raise ImportError(
                "scikit-learn is required for AutoencoderDetector. "
                f"Install it with: pip install scikit-learn\n"
                f"Original error: {_SKLEARN_MISSING_MSG}"
            )

    @classmethod
    def _check_sklearn_cls(cls) -> None:
        cls._check_sklearn()

    def _check_fitted(self) -> None:
        if not self._fitted or self._model is None:
            raise RuntimeError(
                "Detector is not fitted. Call fit() or load() first."
            )
