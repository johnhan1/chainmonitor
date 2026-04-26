# ChainMonitor Rules

Priority tiers: **P0 (per-turn)** > **P1 (end-of-task)** > **P2 (linter/pre-commit)**.

---

## P0 — Safety & Correctness (every response)

1. Before any Python operation, verify `.venv` exists (`Test-Path .\.venv\Scripts\python.exe`). If not, STOP.
2. Python commands must use `.\.venv\Scripts\python -m <module>` only. Never global `python`/`pip`.
3. Database access goes through `src/shared/db/` only. No raw SQL outside it.
4. Never swallow exceptions. Log and convert to consistent error response (`message` + `trace_id`).
5. External HTTP calls must have timeouts. High-risk endpoints must have auth/rate-limit.
6. New config goes into `src/shared/config.py::Settings` (`CM_` prefix). No `os.getenv` for business config.

## P1 — Architecture & Quality (check at task end)

7. Strict layering: routing layer has no business logic, business layer has no raw SQL, no cross-layer internal calls. Module responsibilities in `AGENTS.md`.
8. Cross-layer data uses Pydantic models from `src/shared/schemas/`. Serialize with `model_dump()`.
9. Python 3.11/3.12 compatible. New modules: `from __future__ import annotations`. Full type annotations. Line length ≤ 100.
10. Schema changes require Alembic migration (upgrade + downgrade).
11. At least 1 test per change. High-risk logic needs success + failure paths.
12. Update docs when changing config/scripts/APIs/monitoring.

## P2 — Style (linter/pre-commit handles)

13. Naming: functions/variables `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
14. Import order follows ruff/isort. No unused imports.

---

## Behavior Guidelines

Adapted from Karpathy Guidelines. When in conflict with P0, P0 wins.

> Tradeoff: These bias toward caution over speed. For trivial tasks (typo fixes, formatting), use judgment.

### Think Before Coding
- State assumptions explicitly. If unsure, ask. Don't guess.
- If multiple interpretations exist, present them — don't silently pick one.
- If a simpler approach exists, say so. Push back when warranted.
- If stuck, stop and name what's confusing.

### Simplicity First
- Minimum code that solves the problem. Nothing speculative.
- No abstractions (classes, factories, interfaces) for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.
- Self-check: "Would a senior engineer call this overcomplicated?" If yes, simplify.

### Surgical Changes
- Touch only what you must. Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken. Match existing style.
- Clean up imports/variables/functions YOUR changes made unused. Don't touch pre-existing dead code.
- Test: every changed line traces directly to the user's request.

### Goal-Driven Execution
- Turn fuzzy requests into verifiable goals:
  - "Add validation" → "Write tests for invalid inputs, then make them pass"
  - "Fix the bug" → "Write a reproduction test, then make it pass"
  - "Refactor X" → "Ensure tests pass before and after"
- Strong success criteria let you iterate independently. Weak criteria ("make it work") invite endless clarification.
- For multi-step tasks, state a brief plan upfront with verification per step:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

### Independent Judgment
- When the user asks for your opinion/analysis (not a direct command), think independently first. State your own conclusion before acknowledging the user's stated view.
- If the user says something you disagree with or that seems architecturally wrong, push back—don't nod through.
- Bias toward being usefully correct, not agreeably wrong.
- After giving your independent view, then ask "that said, do you want to go a different direction?" — but lead with your best judgment.

### Signal of Success
You're doing it right when: fewer unrelated changes in diffs, fewer rewrites due to overcomplication, clarifying questions come before implementation rather than after mistakes.
