from __future__ import annotations

from pathlib import Path


def test_ci_workflow_contains_ai_review_gate_and_artifact_upload() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "name: AI Review Repair Gate" in workflow
    assert "./scripts/ci-ai-review-repair-gate.ps1" in workflow
    assert "name: Upload AI Review Report" in workflow
    assert "ai-review-repair-report" in workflow


def test_ci_gate_script_emits_required_observability_fields() -> None:
    script = Path("scripts/ci-ai-review-repair-gate.ps1").read_text(encoding="utf-8")

    assert "trace_id" in script
    assert "pass_rate" in script
    assert "failure_reason_distribution" in script
