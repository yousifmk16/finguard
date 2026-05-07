"""
MLQ-02: Tests for the model evaluation workflow.

Pin down the contract that this script:
  1. Reads the MLQ-01 calibration JSON when available, with fallback.
  2. Builds the same validation set MLQ-01 tuned on (no leakage of new data).
  3. Computes recall / F1 / precision deterministically.
  4. Writes both ``evaluation.json`` and ``MODEL_EVALUATION_REPORT.md``
     with stable filenames so each run overwrites rather than accumulating.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.src.evaluation.run_evaluation import (
    EvaluationConfig,
    _FALLBACK_THRESHOLD,
    main,
    resolve_threshold,
    run,
)


# ---------------------------------------------------------------------------
# Threshold resolution
# ---------------------------------------------------------------------------


class TestResolveThreshold:
    def test_explicit_override_wins(self, tmp_path: Path) -> None:
        # Create a calibration file that says 0.30 — explicit must override it.
        cal = tmp_path / "threshold_calibration.json"
        cal.write_text(json.dumps({"best_threshold": 0.30}), encoding="utf-8")
        threshold, source = resolve_threshold(cal, explicit=0.42)
        assert threshold == 0.42
        assert "explicit" in source.lower()

    def test_reads_calibration_json_when_present(self, tmp_path: Path) -> None:
        cal = tmp_path / "threshold_calibration.json"
        cal.write_text(json.dumps({"best_threshold": 0.37}), encoding="utf-8")
        threshold, source = resolve_threshold(cal)
        assert threshold == 0.37
        assert "MLQ-01" in source

    def test_falls_back_when_calibration_missing(self, tmp_path: Path) -> None:
        threshold, source = resolve_threshold(tmp_path / "missing.json")
        assert threshold == _FALLBACK_THRESHOLD
        assert "fallback" in source.lower()

    def test_falls_back_when_calibration_malformed(self, tmp_path: Path) -> None:
        cal = tmp_path / "broken.json"
        cal.write_text("not json", encoding="utf-8")
        threshold, source = resolve_threshold(cal)
        assert threshold == _FALLBACK_THRESHOLD

    def test_falls_back_when_key_missing(self, tmp_path: Path) -> None:
        cal = tmp_path / "nokey.json"
        cal.write_text(json.dumps({"other": 1}), encoding="utf-8")
        threshold, source = resolve_threshold(cal)
        assert threshold == _FALLBACK_THRESHOLD


# ---------------------------------------------------------------------------
# run() — full workflow
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_produces_supervised_metrics(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        assert out.precision is not None
        assert out.recall is not None
        assert out.f1 is not None
        # On the curated validation set: recall well above zero, precision high.
        assert 0.0 < out.recall <= 1.0
        assert 0.0 < out.precision <= 1.0
        assert 0.0 < out.f1 <= 1.0

    def test_run_validation_set_has_realistic_anomaly_rate(
        self, tmp_path: Path
    ) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        rate = out.n_true_anomalies / max(out.n_samples, 1)
        assert 0.02 <= rate <= 0.10

    def test_run_no_write_creates_no_files(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path / "out",
                calibration_path=tmp_path / "missing.json",
            ),
            write=False,
        )
        assert out.json_path is None
        assert out.md_path is None
        assert not (tmp_path / "out").exists()

    def test_run_writes_both_artifacts(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        assert out.json_path is not None
        assert out.md_path is not None
        assert out.json_path.name == "evaluation.json"
        assert out.md_path.name == "MODEL_EVALUATION_REPORT.md"
        assert out.json_path.exists()
        assert out.md_path.exists()

    def test_run_stable_filenames_overwrite(self, tmp_path: Path) -> None:
        """Re-running must overwrite, not accumulate (no timestamped names)."""
        cfg = EvaluationConfig(
            threshold=0.30,
            output_dir=tmp_path,
            calibration_path=tmp_path / "missing.json",
        )
        run(cfg, write=True)
        run(cfg, write=True)
        # Exactly two artifacts, regardless of how many times we ran.
        names = {f.name for f in tmp_path.iterdir()}
        assert names == {"MODEL_EVALUATION_REPORT.md", "evaluation.json"}

    def test_run_uses_calibration_threshold_by_default(self, tmp_path: Path) -> None:
        cal = tmp_path / "threshold_calibration.json"
        cal.write_text(json.dumps({"best_threshold": 0.42}), encoding="utf-8")
        out = run(
            EvaluationConfig(output_dir=tmp_path, calibration_path=cal),
            write=False,
        )
        assert out.threshold == 0.42
        assert "MLQ-01" in out.threshold_source


# ---------------------------------------------------------------------------
# JSON shape
# ---------------------------------------------------------------------------


class TestJsonShape:
    def test_json_has_required_keys(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        for key in (
            "generated_at",
            "n_rows",
            "model_meta",
            "score_stats",
            "detection",
            "supervised",
            "type_breakdown",
            "signal_contributions",
        ):
            assert key in data, f"missing top-level key: {key}"

    def test_json_supervised_metrics_match_summary(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        sv = data["supervised"]
        assert sv["precision"] == out.precision
        assert sv["recall"] == out.recall
        assert sv["f1"] == out.f1


# ---------------------------------------------------------------------------
# Markdown shape
# ---------------------------------------------------------------------------


class TestMarkdownShape:
    def test_markdown_includes_headline_metrics(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        text = out.md_path.read_text(encoding="utf-8")

        assert "MLQ-02" in text
        assert "Headline metrics" in text
        assert f"{out.precision:.4f}" in text
        assert f"{out.recall:.4f}" in text
        assert f"{out.f1:.4f}" in text

    def test_markdown_calls_out_threshold_source(self, tmp_path: Path) -> None:
        out = run(
            EvaluationConfig(
                threshold=0.30,
                output_dir=tmp_path,
                calibration_path=tmp_path / "missing.json",
            ),
            write=True,
        )
        text = out.md_path.read_text(encoding="utf-8")
        assert "anomaly_threshold = 0.3000" in text
        assert "explicit" in text.lower() or "fallback" in text.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_runs_produce_same_metrics(self, tmp_path: Path) -> None:
        cfg1 = EvaluationConfig(
            threshold=0.30,
            output_dir=tmp_path / "a",
            calibration_path=tmp_path / "missing.json",
        )
        cfg2 = EvaluationConfig(
            threshold=0.30,
            output_dir=tmp_path / "b",
            calibration_path=tmp_path / "missing.json",
        )
        out1 = run(cfg1, write=False)
        out2 = run(cfg2, write=False)

        assert out1.precision == out2.precision
        assert out1.recall == out2.recall
        assert out1.f1 == out2.f1
        assert out1.n_samples == out2.n_samples
        assert out1.n_true_anomalies == out2.n_true_anomalies


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_runs_end_to_end(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Use --threshold to avoid depending on the repo's calibration JSON.
        rc = main([
            "--threshold", "0.30",
            "--output", str(tmp_path),
            "--n", "500",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        result = json.loads(captured.out)
        assert "precision" in result
        assert "recall" in result
        assert "f1" in result
        assert (tmp_path / "evaluation.json").exists()
        assert (tmp_path / "MODEL_EVALUATION_REPORT.md").exists()

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
        assert not (tmp_path / "evaluation.json").exists()
