---
name: "ai-review-repair"
description: "Orchestrates automated code review and targeted repair loops with clear stop boundaries. Invoke after AI coding or before merge/CI gate decisions."
---

# AI Review Repair

## Purpose
This skill orchestrates a repeatable loop:
`generate patch -> run checks -> emit structured issues -> targeted repair -> re-check`.

The skill only handles orchestration and stop decisions.
Actual checks are executed by existing CI toolchain commands.

## When To Invoke
- After AI or human-assisted code generation that may need quality gates.
- Before merge when lint/type/test/security/architecture checks must pass.
- When a failed CI run needs iterative, scoped repair with traceable records.

## Input Contract
Use a single input object with the following fields:

```json
{
  "scope": {
    "paths": ["src/**", "tests/**"],
    "allow_edit_paths": ["src/**", "tests/**"]
  },
  "gates": {
    "hard": ["lint", "type", "test", "security", "architecture"],
    "soft_score_threshold": 85
  },
  "iteration": {
    "max_rounds": 4,
    "no_improvement_rounds": 2,
    "min_score_delta": 1
  },
  "policy": {
    "fix_failed_items_only": true,
    "require_trace_id": true
  }
}
```

Input field notes:
- `scope.paths`: code scope for checks and summaries.
- `scope.allow_edit_paths`: allowed modification boundary.
- `gates.hard`: mandatory checks that must all pass.
- `gates.soft_score_threshold`: quality score threshold after hard gates pass.
- `iteration.max_rounds`: absolute loop limit.
- `iteration.no_improvement_rounds`: consecutive rounds with no meaningful gain.
- `iteration.min_score_delta`: minimal score increase considered improvement.
- `policy.fix_failed_items_only`: disallow unrelated edits.
- `policy.require_trace_id`: every round must include traceability ID.

## Output Contract
Return one structured output object:

```json
{
  "status": "passed | escalated | failed",
  "trace_id": "string",
  "checks": [
    {
      "name": "lint | type | test | security | architecture",
      "passed": true,
      "exit_code": 0,
      "duration_ms": 0,
      "evidence": "string"
    }
  ],
  "summary": {
    "rounds_used": 0,
    "hard_gates_passed": false,
    "quality_score": 0,
    "threshold": 85,
    "quality_delta_total": 0
  },
  "issues": [
    {
      "issue_id": "string",
      "severity": "critical | high | medium | low",
      "rule": "string",
      "file": "string",
      "evidence": "string",
      "expected_fix": "string",
      "acceptance_criteria": "string",
      "status": "open | fixed | accepted_risk"
    }
  ],
  "repairs": [
    {
      "round": 1,
      "changed_files": ["string"],
      "fixed_issue_ids": ["string"],
      "score_before": 0,
      "score_after": 0,
      "score_delta": 0
    }
  ],
  "escalation": {
    "required": false,
    "reason": "max_rounds_reached | no_improvement | manual_override | none"
  }
}
```

Output field notes:
- `checks`: raw gate execution outcomes used for deterministic orchestration.
- `summary.quality_delta_total`: final score minus first round score.
- `repairs[].score_delta`: per-round quality change used for no-improvement checks.
- `issues`: must be sorted by severity first (`critical > high > medium > low`), then stable by `rule + file`.

## Stop Boundaries
Stop with `passed` when:
- all hard gates pass, and
- quality score >= `soft_score_threshold`.

Stop with `escalated` when:
- rounds reached `max_rounds`, or
- no improvement for `no_improvement_rounds` consecutive rounds.

Stop with `failed` when:
- required check execution cannot be completed reliably (for example tool failure),
- and escalation path is unavailable.

## Execution Skeleton
1. Initialize `trace_id`, load input contract, validate required fields.
2. Run hard gates and compute quality score snapshot.
3. If pass condition met, emit output and stop.
4. Build structured issue list from failed items only.
5. Perform scoped repair inside `allow_edit_paths` only.
6. Re-run checks, compare score delta, append round record.
7. Re-evaluate stop boundaries; continue or escalate.
8. Emit final structured output.

## Review Orchestration (Task 2)
### Gate Steps (Task 2.1)
Run checks in deterministic order and record every result in `checks`:
1. `lint`
2. `type`
3. `test`
4. `security`
5. `architecture`

Recommended command mapping (replace with repository-specific commands):
- `lint`: formatter/linter command from CI
- `type`: static type checker command from CI
- `test`: test suite command from CI
- `security`: SAST/dependency/security check command from CI
- `architecture`: architecture/rule compliance command from CI

### Structured Aggregation (Task 2.2)
Normalize every failing signal into one issue item:
- `issue_id`: stable id, for example `"{rule}:{file}:{line}"`.
- `severity`: `critical | high | medium | low`.
- `rule`: failing rule/check id.
- `file`: file path.
- `evidence`: minimal reproducible evidence from tool output.
- `expected_fix`: concrete remediation expectation.
- `acceptance_criteria`: objective pass condition after fix.
- `status`: `open | fixed | accepted_risk`.

Aggregation rules:
- Merge duplicate findings from different tools by `rule + file + normalized evidence`.
- Keep one issue per actionable failure unit.
- Discard non-actionable noise (flaky logs without deterministic evidence).

### Severity-Ordered Issues (Task 2.3)
Always output `issues` sorted by:
1. severity rank (`critical > high > medium > low`)
2. deterministic tie-breaker (`rule`, then `file`, then `issue_id`)

This order is mandatory input to targeted repair prompts.

## Targeted Repair Loop (Task 3)
### Failed-Items-Only Prompt Template (Task 3.1)
Use this strict template each round:

```text
Round: <n>, Trace: <trace_id>
Allowed edit scope: <allow_edit_paths>
Fix ONLY the following open issues:
<issue list in severity order>

Constraints:
1) Do not edit files outside allowed scope.
2) Do not modify code unrelated to listed issues.
3) Keep patch minimal and explain mapping: issue_id -> changed files.
4) Return changed_files and fixed_issue_ids.
```

### Re-Review and Score Delta (Task 3.2)
After each repair:
1. Re-run all hard gates.
2. Recompute quality score using the same scoring function.
3. Record `score_before`, `score_after`, `score_delta`.
4. Update `summary.quality_delta_total`.
5. Mark issues as `fixed` only when corresponding evidence disappears.

No-improvement detection:
- Round is "improved" only if `score_delta >= min_score_delta`.
- If improved condition is not met for `no_improvement_rounds` consecutive rounds, escalate.

### Stop or Escalate (Task 3.3)
Stop with `passed` when:
- all hard gates pass, and
- score meets `soft_score_threshold`.

Stop with `escalated` when:
- `max_rounds` reached, or
- no-improvement threshold reached.

Escalation output must include:
- `escalation.required = true`
- `escalation.reason`
- unresolved issues list (still `open`)
- full repair history with score changes

## Guardrails
- Never modify files outside `scope.allow_edit_paths`.
- Never repair items not present in current `issues`.
- Always preserve per-round logs and `trace_id`.
- Keep output schema stable for CI consumers.

## CI Integration (Task 4)
### CI Entry and Blocking (Task 4.1)
GitHub Actions entry:
- Workflow: `.github/workflows/ci.yml`
- Gate step: `AI Review Repair Gate`
- Script: `scripts/ci-ai-review-repair-gate.ps1`

Blocking rule:
- The gate executes hard checks in order (`lint`, `test`).
- CI is blocked when any check fails.

### Observability Outputs (Task 4.2)
The CI gate emits:
- `rounds` (current CI path uses one deterministic round),
- `pass_rate` (hard gate pass ratio),
- `failure_reason_distribution` (failed checks grouped by gate name).

Artifacts:
- `.artifacts/ai-review-repair/report.json`
- `.artifacts/ai-review-repair/summary.md`

### Traceability (Task 4.3)
Each CI run generates:
- `trace_id` in report payload and summary,
- per-check `evidence` and `duration_ms`,
- uploaded artifact `ai-review-repair-report` for later incident review.
