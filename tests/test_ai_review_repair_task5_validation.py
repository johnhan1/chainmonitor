from __future__ import annotations

from pathlib import Path


def test_task5_success_path_contract() -> None:
    skill_doc = Path(".trae/skills/ai-review-repair/SKILL.md").read_text(encoding="utf-8")

    required_markers = [
        "Stop with `passed` when:",
        "- all hard gates pass, and",
        "- quality score >= `soft_score_threshold`.",
        '"status": "passed | escalated | failed"',
    ]

    for marker in required_markers:
        assert marker in skill_doc, f"missing success marker: {marker}"


def test_task5_failure_and_escalation_path_contract() -> None:
    skill_doc = Path(".trae/skills/ai-review-repair/SKILL.md").read_text(encoding="utf-8")

    escalation_markers = [
        "Stop with `escalated` when:",
        "- rounds reached `max_rounds`, or",
        "- no improvement for `no_improvement_rounds` consecutive rounds.",
        '"reason": "max_rounds_reached | no_improvement | manual_override | none"',
    ]
    failed_markers = [
        "Stop with `failed` when:",
        "- required check execution cannot be completed reliably",
        "- and escalation path is unavailable.",
    ]

    for marker in escalation_markers + failed_markers:
        assert marker in skill_doc, f"missing failure/escalation marker: {marker}"


def test_task5_non_regression_on_structured_output_and_ci_traceability() -> None:
    skill_doc = Path(".trae/skills/ai-review-repair/SKILL.md").read_text(encoding="utf-8")
    ci_script = Path("scripts/ci-ai-review-repair-gate.ps1").read_text(encoding="utf-8")

    issue_fields = [
        '"issue_id": "string"',
        '"severity": "critical | high | medium | low"',
        '"rule": "string"',
        '"file": "string"',
        '"evidence": "string"',
        '"expected_fix": "string"',
        '"acceptance_criteria": "string"',
    ]
    quality_and_round_fields = [
        '"quality_score": 0',
        '"threshold": 85',
        '"quality_delta_total": 0',
        '"score_before": 0',
        '"score_after": 0',
        '"score_delta": 0',
    ]
    ci_observability_fields = [
        "trace_id",
        "pass_rate",
        "failure_reason_distribution",
    ]

    for marker in issue_fields + quality_and_round_fields:
        assert marker in skill_doc, f"missing non-regression marker in skill doc: {marker}"
    for marker in ci_observability_fields:
        assert marker in ci_script, f"missing non-regression marker in ci script: {marker}"
