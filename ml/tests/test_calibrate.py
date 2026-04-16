"""
ENS-03: Unit tests for the threshold calibration script.

Covers:
  CalibrationConfig   – validation
  ThresholdCalibrator – supervised sweep, unsupervised fallback, pick_best
  CalibrationResult   – to_dict(), report_text(), save() / load_threshold()
  CLI                 – --synthetic, --no-save flags
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.src.inference.calibrate import (
    CalibrationConfig,
    CalibrationResult,
    ThresholdCalibrator,
    ThresholdRow,
    main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_scored_df(
    n: int = 200,
    anomaly_rate: float = 0.10,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Synthetic scored DataFrame with clean separation between normal and
    anomaly scores so sweep tests have predictable results.

    Normals:   anomaly_score ~ Uniform(0.10, 0.45)
    Anomalies: anomaly_score ~ Uniform(0.70, 0.95)
    """
    rng = np.random.default_rng(seed)
    n_anom = max(1, int(n * anomaly_rate))
    n_norm = n - n_anom

    normal_scores = rng.uniform(0.10, 0.45, n_norm)
    anom_scores = rng.uniform(0.70, 0.95, n_anom)

    scores = np.concatenate([normal_scores, anom_scores])
    labels = np.concatenate([np.zeros(n_norm, int), np.ones(n_anom, int)])

    idx = rng.permutation(n)
    return pd.DataFrame({
        "anomaly_score": scores[idx],
        "is_anomaly": labels[idx],
    })


def _clean_grid():
    """A small threshold grid that spans the test score distributions."""
    return [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


# ---------------------------------------------------------------------------
# CalibrationConfig
# ---------------------------------------------------------------------------


class TestCalibrationConfig:

    def test_default_target_metric(self) -> None:
        assert CalibrationConfig().target_metric == "f1"

    def test_invalid_target_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="target_metric"):
            CalibrationConfig(target_metric="roc_auc")

    def test_invalid_threshold_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold_grid"):
            CalibrationConfig(threshold_grid=[0.0, 0.5])

    def test_invalid_threshold_one_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold_grid"):
            CalibrationConfig(threshold_grid=[0.5, 1.0])

    def test_invalid_expected_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="expected_anomaly_rate"):
            CalibrationConfig(expected_anomaly_rate=0.0)

    def test_valid_custom_config(self) -> None:
        cfg = CalibrationConfig(
            threshold_grid=[0.4, 0.6, 0.8],
            target_metric="recall",
            expected_anomaly_rate=0.10,
        )
        assert cfg.target_metric == "recall"
        assert len(cfg.threshold_grid) == 3


# ---------------------------------------------------------------------------
# ThresholdCalibrator — supervised mode
# ---------------------------------------------------------------------------


class TestSupervisedCalibration:

    def _cal(self, metric: str = "f1") -> ThresholdCalibrator:
        return ThresholdCalibrator(
            CalibrationConfig(
                threshold_grid=_clean_grid(),
                target_metric=metric,
            )
        )

    def test_returns_calibration_result(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert isinstance(result, CalibrationResult)

    def test_method_is_supervised_with_labels(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert result.method == "supervised"

    def test_best_threshold_in_grid(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert result.best_threshold in _clean_grid()

    def test_best_threshold_detects_anomalies(self) -> None:
        """With clean score separation, best threshold should have recall > 0."""
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert result.metrics_at_best.recall > 0.0

    def test_f1_metric_picks_high_f1(self) -> None:
        """The selected threshold's F1 should be the maximum in the sweep."""
        df = _make_scored_df()
        result = self._cal("f1").calibrate(df)
        max_f1 = result.sweep["f1"].max()
        assert abs(result.metrics_at_best.f1 - max_f1) < 1e-9

    def test_recall_metric_picks_high_recall(self) -> None:
        df = _make_scored_df()
        result = self._cal("recall").calibrate(df)
        max_recall = result.sweep["recall"].max()
        assert abs(result.metrics_at_best.recall - max_recall) < 1e-9

    def test_precision_metric_picks_high_precision(self) -> None:
        df = _make_scored_df()
        result = self._cal("precision").calibrate(df)
        max_prec = result.sweep.loc[
            result.sweep["recall"] >= CalibrationConfig().min_recall, "precision"
        ].max()
        assert result.metrics_at_best.precision >= max_prec - 1e-9

    def test_sweep_row_count_matches_grid(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert len(result.sweep) == len(_clean_grid())

    def test_sweep_thresholds_match_grid(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        assert list(result.sweep["threshold"]) == _clean_grid()

    def test_sweep_columns(self) -> None:
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        for col in ["threshold", "precision", "recall", "f1", "tp", "fp", "fn",
                    "n_flagged", "flag_rate"]:
            assert col in result.sweep.columns

    def test_confusion_matrix_consistent(self) -> None:
        """TP + FP == n_flagged for every row in the supervised sweep."""
        df = _make_scored_df()
        result = self._cal().calibrate(df)
        for _, row in result.sweep.iterrows():
            assert int(row["tp"]) + int(row["fp"]) == int(row["n_flagged"])

    def test_n_samples_correct(self) -> None:
        n = 150
        df = _make_scored_df(n=n)
        result = self._cal().calibrate(df)
        assert result.n_samples == n

    def test_n_true_anomalies_correct(self) -> None:
        df = _make_scored_df(n=200, anomaly_rate=0.10)
        result = self._cal().calibrate(df)
        assert result.n_true_anomalies == int(df["is_anomaly"].sum())

    def test_target_metric_recorded(self) -> None:
        result = self._cal("precision").calibrate(_make_scored_df())
        assert result.target_metric == "precision"

    def test_y_true_arg_overrides_column(self) -> None:
        """Explicit y_true takes precedence over the label column in df."""
        df = _make_scored_df()
        # Corrupt the in-df labels — calibrator should use y_true instead
        df["is_anomaly"] = 0
        real_labels = pd.Series(
            np.where(df["anomaly_score"] >= 0.70, 1, 0), index=df.index
        )
        result = self._cal().calibrate(df, y_true=real_labels)
        assert result.n_true_anomalies == int(real_labels.sum())

    def test_missing_score_col_raises(self) -> None:
        df = pd.DataFrame({"is_anomaly": [0, 1, 0]})
        with pytest.raises(ValueError, match="anomaly_score"):
            ThresholdCalibrator().calibrate(df)

    def test_f1_tie_breaks_prefer_higher_threshold(self) -> None:
        """When multiple thresholds share max F1, the highest is chosen."""
        # Build scores where all thresholds above 0.50 produce identical F1
        scores = [0.80, 0.81, 0.82, 0.10, 0.11, 0.12]
        labels = [1, 1, 1, 0, 0, 0]
        df = pd.DataFrame({"anomaly_score": scores, "is_anomaly": labels})
        cfg = CalibrationConfig(threshold_grid=[0.50, 0.60, 0.70])
        result = ThresholdCalibrator(cfg).calibrate(df)
        # All three thresholds should give identical TP=3, FP=0 → F1=1.0
        assert result.best_threshold == 0.70

    def test_recall_tie_breaks_prefer_lower_threshold(self) -> None:
        """When multiple thresholds share max recall, the lowest is chosen."""
        scores = [0.80, 0.81, 0.82, 0.10, 0.11, 0.12]
        labels = [1, 1, 1, 0, 0, 0]
        df = pd.DataFrame({"anomaly_score": scores, "is_anomaly": labels})
        cfg = CalibrationConfig(
            threshold_grid=[0.50, 0.60, 0.70],
            target_metric="recall",
        )
        result = ThresholdCalibrator(cfg).calibrate(df)
        assert result.best_threshold == 0.50


# ---------------------------------------------------------------------------
# ThresholdCalibrator — unsupervised mode
# ---------------------------------------------------------------------------


class TestUnsupervisedCalibration:

    def _cal(self) -> ThresholdCalibrator:
        return ThresholdCalibrator(
            CalibrationConfig(
                threshold_grid=_clean_grid(),
                expected_anomaly_rate=0.10,
            )
        )

    def test_method_is_unsupervised_without_labels(self) -> None:
        df = pd.DataFrame({"anomaly_score": [0.3, 0.5, 0.7, 0.9]})
        result = self._cal().calibrate(df)
        assert result.method == "unsupervised"

    def test_best_threshold_in_valid_range(self) -> None:
        df = pd.DataFrame({"anomaly_score": np.linspace(0.1, 0.95, 100).tolist()})
        result = self._cal().calibrate(df)
        assert 0.0 < result.best_threshold < 1.0

    def test_n_true_anomalies_zero_unsupervised(self) -> None:
        df = pd.DataFrame({"anomaly_score": [0.3, 0.5, 0.7]})
        result = self._cal().calibrate(df)
        assert result.n_true_anomalies == 0

    def test_sweep_f1_is_nan_unsupervised(self) -> None:
        df = pd.DataFrame({"anomaly_score": [0.3, 0.5, 0.7, 0.9]})
        result = self._cal().calibrate(df)
        assert result.sweep["f1"].isna().all()

    def test_sweep_flag_rate_decreases_with_threshold(self) -> None:
        scores = list(np.linspace(0.1, 0.95, 100))
        df = pd.DataFrame({"anomaly_score": scores})
        result = self._cal().calibrate(df)
        rates = result.sweep["flag_rate"].tolist()
        for a, b in zip(rates, rates[1:]):
            assert a >= b - 1e-9, "flag_rate should be non-increasing with threshold"


# ---------------------------------------------------------------------------
# CalibrationResult serialisation
# ---------------------------------------------------------------------------


class TestCalibrationResultSerialisation:

    def _result(self) -> CalibrationResult:
        df = _make_scored_df()
        return ThresholdCalibrator(
            CalibrationConfig(threshold_grid=_clean_grid())
        ).calibrate(df)

    def test_to_dict_has_expected_keys(self) -> None:
        d = self._result().to_dict()
        for key in ["generated_at", "method", "target_metric",
                    "best_threshold", "n_samples", "n_true_anomalies",
                    "metrics_at_best", "sweep"]:
            assert key in d

    def test_best_threshold_in_dict(self) -> None:
        result = self._result()
        assert result.to_dict()["best_threshold"] == result.best_threshold

    def test_sweep_in_dict_is_list(self) -> None:
        d = self._result().to_dict()
        assert isinstance(d["sweep"], list)
        assert len(d["sweep"]) == len(_clean_grid())

    def test_report_text_contains_threshold(self) -> None:
        result = self._result()
        text = result.report_text()
        assert f"{result.best_threshold:.4f}" in text

    def test_report_text_contains_header(self) -> None:
        text = self._result().report_text()
        assert "ENS-03" in text

    def test_report_text_marks_best_row(self) -> None:
        text = self._result().report_text()
        assert "◄" in text

    def test_save_writes_json(self, tmp_path: Path) -> None:
        result = self._result()
        saved = result.save(str(tmp_path))
        assert saved.exists()
        data = json.loads(saved.read_text())
        assert data["best_threshold"] == result.best_threshold

    def test_load_threshold_round_trips(self, tmp_path: Path) -> None:
        result = self._result()
        saved = result.save(str(tmp_path))
        loaded = ThresholdCalibrator.load_threshold(saved)
        assert math.isclose(loaded, result.best_threshold, rel_tol=1e-9)

    def test_load_threshold_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ThresholdCalibrator.load_threshold(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI:

    def test_synthetic_flag_exits_zero(self, tmp_path: Path) -> None:
        rc = main(["--synthetic", "--output", str(tmp_path), "--quiet"])
        assert rc == 0

    def test_synthetic_writes_json(self, tmp_path: Path) -> None:
        main(["--synthetic", "--output", str(tmp_path), "--quiet"])
        assert (tmp_path / "threshold_calibration.json").exists()

    def test_no_save_skips_json(self, tmp_path: Path) -> None:
        main(["--synthetic", "--output", str(tmp_path), "--no-save", "--quiet"])
        assert not (tmp_path / "threshold_calibration.json").exists()

    def test_recall_metric_cli(self, tmp_path: Path) -> None:
        main(["--synthetic", "--metric", "recall",
              "--output", str(tmp_path), "--quiet"])
        data = json.loads((tmp_path / "threshold_calibration.json").read_text())
        assert data["target_metric"] == "recall"

    def test_missing_input_file_returns_one(self, tmp_path: Path) -> None:
        rc = main(["--input", str(tmp_path / "ghost.csv"),
                   "--output", str(tmp_path), "--quiet"])
        assert rc == 1

    def test_input_csv(self, tmp_path: Path) -> None:
        df = _make_scored_df(n=100)
        csv_path = tmp_path / "scored.csv"
        df.to_csv(csv_path, index=False)
        rc = main(["--input", str(csv_path),
                   "--output", str(tmp_path), "--quiet"])
        assert rc == 0
        data = json.loads((tmp_path / "threshold_calibration.json").read_text())
        assert "best_threshold" in data
