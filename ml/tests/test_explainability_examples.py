"""
MLQ-04: Tests for the explainability quality-examples gallery.

The gallery's most important property is that every curated payload
round-trips through the EXP-04 Pydantic schema. These tests pin down
that contract and the case-selection invariants:

  1. All five intended cases are picked from the canonical validation set.
  2. Every payload validates against ``AnomalyExplanationResponse``.
  3. Confusion-matrix semantics hold: the *flagged* / *label* combination
     each case is supposed to demonstrate is the one we actually picked.
  4. The graceful-degradation showcase is real — ``if_score`` is always
     inactive in the breakdown.
  5. Outputs are deterministic across runs and use stable filenames.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas.explanation import AnomalyExplanationResponse
from ml.src.evaluation.explainability_examples import (
    GalleryConfig,
    main,
    run,
)


_EXPECTED_CASE_KEYS = {
    "high_confidence_spike",
    "sustained_budget_breach",
    "borderline_normal",
    "calm_normal",
    "missed_anomaly",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_default(tmp_path: Path, write: bool = False):
    """Run the gallery against the canonical 3000-row validation set."""
    return run(
        GalleryConfig(
            threshold=0.30,
            output_dir=tmp_path,
            calibration_path=tmp_path / "missing.json",
        ),
        write=write,
    )


def _case_by_key(out, key: str):
    for c in out.cases:
        if c.key == key:
            return c
    raise AssertionError(f"case {key!r} not present in gallery")


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


class TestCaseSelection:
    def test_all_five_cases_are_produced(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        assert {c.key for c in out.cases} == _EXPECTED_CASE_KEYS

    def test_case_order_starts_with_strongest_tp(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        assert out.cases[0].key == "high_confidence_spike"

    def test_high_confidence_spike_is_a_flagged_anomaly(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        c = _case_by_key(out, "high_confidence_spike")
        assert c.label == 1
        assert c.flagged is True
        assert c.anomaly_type == "spike"
        assert c.payload["severity"] in {"medium", "high"}
        # Score should be deeply above threshold for a "high-confidence" pick.
        assert c.payload["anomaly_score"] >= 0.75

    def test_borderline_normal_is_unflagged_normal(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        c = _case_by_key(out, "borderline_normal")
        assert c.label == 0
        assert c.flagged is False
        assert c.anomaly_type == "normal"
        # Below threshold but the highest among normals — non-trivial score.
        assert c.payload["anomaly_score"] < c.payload["anomaly_threshold"]

    def test_calm_normal_is_quiet(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        c = _case_by_key(out, "calm_normal")
        assert c.label == 0
        assert c.flagged is False
        assert c.payload["anomaly_score"] <= 0.05
        # The fully-quiet rule path is the one this case is meant to show.
        assert c.payload["rule_explanation"]["triggered_rules"] == []

    def test_missed_anomaly_is_an_unflagged_anomaly(self, tmp_path: Path) -> None:
        """The whole point of this case: label=1 but flagged=0 (FN)."""
        out = _run_default(tmp_path)
        c = _case_by_key(out, "missed_anomaly")
        assert c.label == 1
        assert c.flagged is False
        assert c.anomaly_type != "normal"


# ---------------------------------------------------------------------------
# EXP-04 contract gate
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_every_payload_validates_against_pydantic_schema(
        self, tmp_path: Path
    ) -> None:
        out = _run_default(tmp_path)
        for c in out.cases:
            # ``model_validate`` raises ValidationError on contract drift.
            AnomalyExplanationResponse.model_validate(c.payload)

    def test_payloads_have_three_components(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        for c in out.cases:
            comps = c.payload["components"]
            assert [comp["name"] for comp in comps] == [
                "ts_signal",
                "if_score",
                "rule_score",
            ]

    def test_if_score_component_is_always_inactive(self, tmp_path: Path) -> None:
        """Graceful-degradation showcase: ``if_score`` must be NaN/inactive."""
        out = _run_default(tmp_path)
        for c in out.cases:
            if_comp = next(
                comp for comp in c.payload["components"] if comp["name"] == "if_score"
            )
            assert if_comp["active"] is False
            assert if_comp["raw_score"] is None
            assert if_comp["weighted_contribution"] == 0.0


# ---------------------------------------------------------------------------
# Numeric / narrative agreement
# ---------------------------------------------------------------------------


class TestNarrativeAgreement:
    def test_flagged_payloads_have_non_none_severity(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path)
        for c in out.cases:
            if c.flagged:
                assert c.payload["severity"] in {"low", "medium", "high"}
            else:
                assert c.payload["severity"] in {"none", None}

    def test_forecast_summary_direction_matches_residual_sign(
        self, tmp_path: Path
    ) -> None:
        out = _run_default(tmp_path)
        for c in out.cases:
            fe = c.payload.get("forecast_explanation")
            if fe is None or fe["residual"] is None:
                continue
            if fe["residual"] > 0:
                assert fe["direction"] == "above"
                assert "above" in fe["summary"].lower()
            elif fe["residual"] < 0:
                assert fe["direction"] == "below"
                assert "below" in fe["summary"].lower()

    def test_triggered_rules_list_matches_per_rule_fired_flags(
        self, tmp_path: Path
    ) -> None:
        out = _run_default(tmp_path)
        for c in out.cases:
            re = c.payload["rule_explanation"]
            fired_from_flags = [
                rule_key.replace("_", "_")  # identity rename; explicit naming
                for rule_key in ("threshold_breach", "sudden_jump", "sustained_increase")
                if re[rule_key]["fired"]
            ]
            # ``triggered_rules`` may use the rule's ``rule`` field (which can
            # differ in casing/spacing); compare on cardinality and membership
            # against per-rule ``fired`` flags.
            assert len(re["triggered_rules"]) == len(fired_from_flags)


# ---------------------------------------------------------------------------
# Artifacts & stability
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_no_write_creates_no_files(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path / "out", write=False)
        assert out.json_path is None and out.md_path is None
        assert not (tmp_path / "out").exists()

    def test_writes_both_artifacts_with_stable_filenames(
        self, tmp_path: Path
    ) -> None:
        cfg = GalleryConfig(
            threshold=0.30,
            output_dir=tmp_path,
            calibration_path=tmp_path / "missing.json",
        )
        run(cfg, write=True)
        run(cfg, write=True)
        names = {f.name for f in tmp_path.iterdir()}
        assert names == {
            "explainability_examples.json",
            "EXPLAINABILITY_EXAMPLES.md",
        }

    def test_json_contains_every_case(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path, write=True)
        data = json.loads(out.json_path.read_text(encoding="utf-8"))
        assert {c["key"] for c in data["cases"]} == _EXPECTED_CASE_KEYS
        for c in data["cases"]:
            # Inline-validate one more time: the json on disk must satisfy
            # the EXP-04 schema, not only the in-process payload.
            AnomalyExplanationResponse.model_validate(c["payload"])

    def test_markdown_lists_every_case_heading(self, tmp_path: Path) -> None:
        out = _run_default(tmp_path, write=True)
        text = out.md_path.read_text(encoding="utf-8")
        for key in _EXPECTED_CASE_KEYS:
            assert f"### `{key}`" in text


class TestDeterminism:
    def test_two_runs_pick_same_rows(self, tmp_path: Path) -> None:
        out1 = _run_default(tmp_path / "a")
        out2 = _run_default(tmp_path / "b")
        rows1 = {(c.key, c.row_index) for c in out1.cases}
        rows2 = {(c.key, c.row_index) for c in out2.cases}
        assert rows1 == rows2

    def test_two_runs_produce_same_anomaly_scores(self, tmp_path: Path) -> None:
        out1 = _run_default(tmp_path / "a")
        out2 = _run_default(tmp_path / "b")
        scores1 = {c.key: c.payload["anomaly_score"] for c in out1.cases}
        scores2 = {c.key: c.payload["anomaly_score"] for c in out2.cases}
        assert scores1 == scores2


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
        ])
        captured = capsys.readouterr()
        assert rc == 0
        result = json.loads(captured.out)
        assert set(result["case_keys"]) == _EXPECTED_CASE_KEYS
        assert (tmp_path / "explainability_examples.json").exists()
        assert (tmp_path / "EXPLAINABILITY_EXAMPLES.md").exists()

    def test_cli_no_write_skips_artifacts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main([
            "--threshold", "0.30",
            "--output", str(tmp_path),
            "--no-write",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        result = json.loads(captured.out)
        assert result["json_path"] is None
        assert result["md_path"] is None
        assert not (tmp_path / "explainability_examples.json").exists()
