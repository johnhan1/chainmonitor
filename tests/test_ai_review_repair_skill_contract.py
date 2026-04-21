from __future__ import annotations

from pathlib import Path


def test_ai_review_repair_skill_includes_task2_task3_contract() -> None:
    skill_doc = Path(".trae/skills/ai-review-repair/SKILL.md").read_text(encoding="utf-8")

    required_markers = [
        "## Review Orchestration (Task 2)",
        "### Gate Steps (Task 2.1)",
        "### Structured Aggregation (Task 2.2)",
        "### Severity-Ordered Issues (Task 2.3)",
        "## Targeted Repair Loop (Task 3)",
        "### Failed-Items-Only Prompt Template (Task 3.1)",
        "### Re-Review and Score Delta (Task 3.2)",
        "### Stop or Escalate (Task 3.3)",
        '"quality_delta_total": 0',
        '"score_delta": 0',
    ]

    for marker in required_markers:
        assert marker in skill_doc, f"missing marker: {marker}"
