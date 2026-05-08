"""
MLQ-03: Tests for the false-positive analysis workflow.

Pin down the contract that this script:
  1. Uses the same threshold resolution chain MLQ-02 does (calibration JSON
     with explicit override and fallback).
  2. Reuses the MLQ-01 / MLQ-02 validation set, so its numbers can be
     compared row-for-row with MODEL_EVALUATION_REPORT.md.
  3. Produces a deterministic confusion matrix, FP / borderline tables,
     and threshold sweep across runs.
  4. Writes ``false_positive_analysis.json`` and
     ``FALSE_POSITIVE_ANALYSIS.md`` with stable filenames.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ml.src.evaluation.false_positive_analysis import (
    FpAnalysisConfig,
    _confusion,
    _sweep_curve,
    main,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hand_built_frame() -> pd.DataFrame:
    """Tiny labeled frame with hand-checkable scores.

    Rows:
      idx  is_anomaly  anomaly_score  outcome_at_0.5
       0   1           0.95            TP
       1   1           0.30            FN
       2   0           0.80            FP
       3   0           0.10            TN
       4   0           0.45            TN
       5   1           0.51            TP
    """
    return pd.DataFrame(
        {
            "is_anomaly": [1, 1, 0, 0, 0, 1],
            "anomaly_score": [0.95, 0.30, 0.80, 0.10, 0.45, 0.51],
            "cost_amount": [400.0, 100.0, 350.0, 50.0, 70.0, 220.0],
            "account_id": ["a", "a", "b", "b", "a", "a"],
            "service": ["s", "s", "s", "s", "s", "s"],
            "region": ["r", "r", "r", "r", "r", "r"],
            "anomaly_type": ["spike", "budget_breach", "normal", "normal", "normal", "spike"],
            "timestamp": ["t0", "t1", "t2", "t3", "t4", "t5"],
        }
    )


# ---------------------------------------------------------------------------
# Confusion-matrix primitive
# ---------------------------------------------------------------------------


class TestConfusion:
    def test_counts_match_hand_calculation(self) -> None:
        h = _confusion(_hand_built_frame(), threshold=0.5)
        assert (h.tp, h.fp, h.fn, h.tn) == (2, 1, 1, 2)
        assert h.precision == pytest.approx(2 / 3, rel=1e-6)
        assert h.recall == pytest.approx(2 / 3, rel=1e-6)
        assert h.false_positive_rate == pytest.approx(1 / 3, rel=1e-6)
        assert h.n_normal == 3
        assert h.n_anomaly == 3

    def test_zero_flagged_keeps_precision_at_one(self) -> None:
        # Threshold above every score — nothing flagged.
        h = _confusion(_hand_built_frame(), threshold=0.99)
        assert h.tp == 0 and h.fp == 0
        assert h.precision == 1.0
        assert h.recall == 0.0


# ---------------------------------------------------------------------------
# Threshold sweep
# ---------------------------------------------------------------------------


class TestSweep:
    def test_sweep_is_monotone_non_increasing_in_flags(self) -> None:
        df = _hand_built_frame()
        rows = _sweep_curve(df, (0.05, 0.5, 0.95))
        flagged = [r.n_flagged for r in rows]
        assert flagged == sorted(flagged, reverse=True)

    def test_sweep_precision_is_none_when_zero_flagged(self) -> None:
        df = _hand_built_frame()
        rows = _sweep_curve(df, (0.99,))
        assert rows[0].n_flagged == 0
        assert rows[0].precision is None


# ---------------------------------------------------------------------------
# Full workflow against the canonical validation set
# ---------------------------------------------------------------------------


class TestRun:
    def test_matches_mlq02_supervised_metrics_at_calibrated_threshold(
        self, tmp_path: Path
    ) -> None:
        """MLQ-03 is a *finer-grained* view of the same evaluation as MLQ-02.

        At an identical threshold the headline confusion counts must match;
        if they ever diverge, one of the two workflows has silently drifted.
        """
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        # Numbers come from MODEL_EVALUATION_REPORT.md @ threshold 0.30.
        assert out.analysis.headline.tp == 108
        assert out.analysis.headline.fp == 0
        assert out.analysis.headline.fn == 40
        assert out.analysis.headline.tn == 2852
        assert out.precision == 1.0

    def test_borderline_normals_strictly_below_threshold(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        for r in out.analysis.borderline_normals:
            assert r.anomaly_score < 0.30
            assert r.anomaly_type == "normal"

    def test_realised_fps_are_normals_at_or_above_threshold(self, tmp_path: Path) -> None:
        # Force a low threshold so we actually have FPs to inspect.
        out = run(
            FpAnalysisConfig(
                threshold=0.10,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        assert out.analysis.headline.fp > 0
        for r in out.analysis.realised_false_positives:
            assert r.anomaly_score >= 0.10
            assert r.anomaly_type == "normal"

    def test_sweep_includes_current_threshold(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        thresholds = {r.threshold for r in out.analysis.sweep}
        assert 0.30 in thresholds

    def test_no_write_creates_no_files(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path / "out",
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        assert out.json_path is None and out.md_path is None
        assert not (tmp_path / "out").exists()

    def test_writes_both_artifacts_with_stable_filenames(self, tmp_path: Path) -> None:
        cfg = FpAnalysisConfig(
            threshold=0.30,
            output_dir=tmp_path,
            calibration_path=tmp_path / "missing.json",
        )
        run(cfg, write=True)
        run(cfg, write=True)
        names = {f.name for f in tmp_path.iterdir()}
        assert names == {"false_positive_analysis.json", "FALSE_POSITIVE_ANALYSIS.md"}


# ---------------------------------------------------------------------------
# JSON shape
# ---------------------------------------------------------------------------


class TestJsonShape:
    def test_json_has_required_top_level_keys(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        for key in (
            "generated_at",
            "threshold",
            "threshold_source",
            "n_rows",
            "headline",
            "realised_false_positives",
            "borderline_normals",
            "sweep",
            "slice_breakdowns",
            "missed_detections_by_type",
            "near_threshold_misses",
            "deeply_missed",
        ):
            assert key in data, f"missing top-level key: {key}"

    def test_json_headline_matches_run_summary(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        head = data["headline"]
        assert head["fp"] == out.n_false_positives
        assert head["fn"] == out.n_false_negatives
        assert head["precision"] == out.precision

    def test_json_slice_breakdowns_cover_default_dimensions(
        self, tmp_path: Path
    ) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        for dim in ("account_id", "service", "region"):
            assert dim in data["slice_breakdowns"]


# ---------------------------------------------------------------------------
# Markdown shape
# ---------------------------------------------------------------------------


class TestMarkdownShape:
    def test_markdown_includes_expected_sections(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        text = out.md_path.read_text(encoding="utf-8")
        assert "MLQ-03" in text
        assert "Headline counts" in text
        assert "Realised false positives" in text
        assert "Borderline normals" in text
        assert "False-positive curve" in text
        assert "False-positive risk by slice" in text

    def test_markdown_calls_out_threshold_source(self, tmp_path: Path) -> None:
        out = run(
            FpAnalysisConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        text = out.md_path.read_text(encoding="utf-8")
        assert "anomaly_threshold = 0.3000" in text
        # Threshold came from explicit override since calibration is absent.
        assert "explicit" in text.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_runs_produce_same_headline(self, tmp_path: Path) -> None:
        cfg1 = FpAnalysisConfig(
            threshold=0.30,
            output_dir=tmp_path / "a",
            calibration_path=tmp_path / "missing.json",
        )
        cfg2 = FpAnalysisConfig(
            threshold=0.30,
            output_dir=tmp_path / "b",
            calibration_path=tmp_path / "missing.json",
        )
        h1 = run(cfg1, write=False).analysis.headline
        h2 = run(cfg2, write=False).analysis.headline
        assert (h1.tp, h1.fp, h1.fn, h1.tn) == (h2.tp, h2.fp, h2.fn, h2.tn)
        assert h1.precision == h2.precision


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_runs_end_to_end(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main([
            "--threshold", "0.30",
            "--output", str(tmp_path),
            "--n", "500",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        result = json.loads(captured.out)
        assert "n_false_positives" in result
        assert "n_false_negatives" in result
        assert (tmp_path / "false_positive_analysis.json").exists()
        assert (tmp_path / "FALSE_POSITIVE_ANALYSIS.md").exists()

    def test_cli_no_write_skips_artifacts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main([
            "--threshold", "0.30",
            "--output", str(tmp_path),
            "--n", "500",
            "--no-write",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        result = json.loads(captured.out)
        assert result["json_path"] is None
        assert result["md_path"] is None
        assert not (tmp_path / "false_positive_analysis.json").exists()
