"""
MLQ-01: Tests for the final threshold tuning workflow.

Locks down the contract that this script is *reproducible* from the same
git revision: anyone who re-runs ``python -m ml.src.tuning.tune_thresholds``
should get the same chosen threshold and the same anomaly-rate distribution
in the validation set.  If a future generator change shifts the answer,
this test fails — making the regression visible at PR time rather than
quietly invalidating the tuned threshold in production.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.src.tuning.tune_thresholds import (
    TuningConfig,
    _normalize_pandas_frequency,
    _attach_anomaly_score,
    build_validation_set,
    main,
    run,
)


# ---------------------------------------------------------------------------
# Validation-set construction
# ---------------------------------------------------------------------------


class TestBuildValidationSet:
    def test_default_config_has_required_columns(self) -> None:
        df = build_validation_set(TuningConfig())
        for col in (
            "account_id",
            "cost_amount",
            "anomaly_score",
            "is_anomaly",
            "anomaly_type",
        ):
            assert col in df.columns, f"missing column: {col}"

    def test_default_config_has_realistic_anomaly_rate(self) -> None:
        """MLQ-01 needs ~5% anomalies, not the >50% the streaming-test config produces."""
        df = build_validation_set(TuningConfig())
        rate = df["is_anomaly"].mean()
        assert 0.02 <= rate <= 0.10, (
            f"validation set anomaly rate {rate:.3f} is outside the [0.02, 0.10] "
            "band — generator config drift or unintended injector enabled?"
        )

    def test_anomaly_score_is_in_unit_interval(self) -> None:
        df = build_validation_set(TuningConfig())
        s = df["anomaly_score"]
        assert s.min() >= 0.0
        assert s.max() <= 1.0
        assert s.notna().all()

    def test_n_samples_override_changes_row_count(self) -> None:
        df_small = build_validation_set(TuningConfig(n_samples=500))
        df_big = build_validation_set(TuningConfig(n_samples=2000))
        assert len(df_small) == 500
        assert len(df_big) == 2000

    def test_validation_set_is_deterministic(self) -> None:
        df1 = build_validation_set(TuningConfig(n_samples=500))
        df2 = build_validation_set(TuningConfig(n_samples=500))
        # Compare the columns we care about — timestamp/event_id may have
        # implementation drift if the generator ever switches uuid generation.
        for col in ("cost_amount", "anomaly_score", "is_anomaly"):
            pd.testing.assert_series_equal(df1[col], df2[col])


# ---------------------------------------------------------------------------
# Score recipe
# ---------------------------------------------------------------------------


class TestAttachAnomalyScore:
    def test_zero_for_constant_series(self) -> None:
        events = pd.DataFrame({
            "account_id": ["a"] * 10,
            "cost_amount": [100.0] * 10,
        })
        scored = _attach_anomaly_score(events)
        assert (scored["anomaly_score"] == 0.0).all()

    def test_extreme_outlier_saturates_to_one(self) -> None:
        # 99 normal rows + 1 huge spike → spike's z-score is well above Z_CAP.
        cost = [100.0] * 99 + [1.0e6]
        events = pd.DataFrame({
            "account_id": ["a"] * 100,
            "cost_amount": cost,
        })
        scored = _attach_anomaly_score(events)
        assert scored["anomaly_score"].iloc[-1] == 1.0
        # Normal rows are well below 1.0.
        assert scored["anomaly_score"].iloc[:99].max() < 0.5

    def test_per_account_grouping_isolates_baselines(self) -> None:
        # Two accounts at very different scales — the spike for account "low"
        # must not be drowned out by account "high"'s baseline.
        df = pd.DataFrame({
            "account_id": ["low"] * 50 + ["high"] * 50,
            "cost_amount": [10.0] * 49 + [50.0] + [1000.0] * 49 + [5000.0],
        })
        scored = _attach_anomaly_score(df)
        # The "low" account spike (50 vs baseline 10) should produce a
        # non-zero score even though it's tiny in absolute terms.
        assert scored["anomaly_score"].iloc[49] > 0.0


# ---------------------------------------------------------------------------
# Frequency normalisation
# ---------------------------------------------------------------------------


class TestFrequencyNormalisation:
    @pytest.mark.parametrize(
        "input_freq,expected",
        [
            ("1H", "1h"),
            ("5T", "5min"),
            ("30S", "30s"),
            ("1h", "1h"),       # already lowercase passes through
            ("1D", "1D"),       # D is unchanged on pandas 2.2
            ("15min", "15min"),
        ],
    )
    def test_aliases_remapped(self, input_freq: str, expected: str) -> None:
        assert _normalize_pandas_frequency(input_freq) == expected


# ---------------------------------------------------------------------------
# Full workflow (run)
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_without_writing_returns_threshold_and_metrics(
        self, tmp_path: Path
    ) -> None:
        out = run(TuningConfig(output_dir=tmp_path), write=False)
        assert 0.0 < out.chosen_threshold < 1.0
        assert out.target_metric == "f1"
        assert out.n_samples > 0
        assert out.n_true_anomalies > 0
        assert out.metrics_at_best["precision"] >= 0.0
        assert out.metrics_at_best["recall"] >= 0.0
        # No files written.
        assert out.artifact_path is None
        assert out.report_path is None
        assert list(tmp_path.iterdir()) == []

    def test_run_writes_both_artifacts(self, tmp_path: Path) -> None:
        out = run(TuningConfig(output_dir=tmp_path), write=True)

        assert out.artifact_path is not None
        assert out.report_path is not None
        assert out.artifact_path.name == "threshold_calibration.json"
        assert out.report_path.name == "THRESHOLD_TUNING_REPORT.md"
        assert out.artifact_path.exists()
        assert out.report_path.exists()

    def test_artifact_json_is_well_formed(self, tmp_path: Path) -> None:
        out = run(TuningConfig(output_dir=tmp_path), write=True)
        data = json.loads(out.artifact_path.read_text(encoding="utf-8"))

        for key in (
            "generated_at",
            "method",
            "target_metric",
            "best_threshold",
            "n_samples",
            "n_true_anomalies",
            "metrics_at_best",
            "sweep",
        ):
            assert key in data, f"missing top-level key: {key}"

        assert data["method"] == "supervised"
        assert 0.0 < data["best_threshold"] < 1.0
        assert data["n_samples"] > 0
        assert data["n_true_anomalies"] > 0
        assert isinstance(data["sweep"], list)
        assert len(data["sweep"]) > 0

    def test_report_markdown_includes_chosen_threshold(self, tmp_path: Path) -> None:
        out = run(TuningConfig(output_dir=tmp_path), write=True)
        text = out.report_path.read_text(encoding="utf-8")

        assert "MLQ-01" in text
        assert "Threshold Tuning Report" in text
        assert f"{out.chosen_threshold:.4f}" in text
        # Sweep table header is rendered.
        assert "threshold" in text and "precision" in text and "f1" in text


# ---------------------------------------------------------------------------
# Determinism — the most important workflow-level invariant
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_runs_produce_same_threshold_and_metrics(
        self, tmp_path: Path
    ) -> None:
        out1 = run(TuningConfig(output_dir=tmp_path / "a"), write=True)
        out2 = run(TuningConfig(output_dir=tmp_path / "b"), write=True)

        assert out1.chosen_threshold == out2.chosen_threshold
        assert out1.n_samples == out2.n_samples
        assert out1.n_true_anomalies == out2.n_true_anomalies
        assert out1.metrics_at_best["tp"] == out2.metrics_at_best["tp"]
        assert out1.metrics_at_best["fp"] == out2.metrics_at_best["fp"]
        assert out1.metrics_at_best["fn"] == out2.metrics_at_best["fn"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_runs_end_to_end(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["--output", str(tmp_path), "--n", "500"])
        captured = capsys.readouterr()

        assert rc == 0
        # Must print parseable JSON on stdout.
        result = json.loads(captured.out)
        assert "chosen_threshold" in result
        assert 0.0 < result["chosen_threshold"] < 1.0
        # Files were written.
        assert (tmp_path / "threshold_calibration.json").exists()
        assert (tmp_path / "THRESHOLD_TUNING_REPORT.md").exists()

    def test_cli_no_write_skips_artifacts(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["--output", str(tmp_path), "--n", "500", "--no-write"])
        captured = capsys.readouterr()

        assert rc == 0
        result = json.loads(captured.out)
        assert result["artifact_path"] is None
        assert result["report_path"] is None
        # Output dir is not created when --no-write is supplied.
        assert not (tmp_path / "threshold_calibration.json").exists()
