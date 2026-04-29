# ChainMonitor — Agent Guide

> ⚠️ Behavioral rules at `.trae/rules/RULES.md`. P0 rules are enforced per-turn.

## Quick start

```powershell
.\scripts\dev.ps1 -Command all          # init → docker up → migrate → test → smoke
.\scripts\dev.ps1 -Command check        # ruff check src tests + pytest -q + pre-commit
.\scripts\dev.ps1 -Command up-lite      # app + postgres + redis only
```

Every command goes through `dev.ps1`. Avoid running sub-scripts (`setup.ps1`, `check.ps1`, etc.) directly — use the `-Command` dispatcher.

## Environment

- Python 3.11 / 3.12 only. `.venv` is **mandatory** — never `pip install` globally.
- `setup.ps1` defaults to `py -3.12`. Override: `.\scripts\dev.ps1 -Command init` (or `setup.ps1 -Python 'py -3.11'`).
- Settings loaded from `.env` + `.env.{dev,staging,prod}` (auto-detected from `CM_APP_ENV`). All vars prefixed `CM_`.
- Config split into 7 domain modules under `src/shared/config/`. Import only what you need: `from src.shared.config.scanner import get_scanner_settings`.
- Copy `.env.example` → `.env` for local dev. Never commit `.env`.

## Project layout

```
src/
  app/                     # FastAPI entrypoint (main.py, services/)
  ingestion/               # Largest package: 3 providers, strategy pattern, resilience layer
    adapters/              # Birdeye/DexScreener/GeckoTerminal provider adapters
    contracts/             # Abstract interfaces, NormalizedPair, PairQualityPolicy
    factory/               # SourceStrategyFactory
    fallback/              # FallbackSourceChain (ordered fallback across providers)
    resilience/            # Circuit breaker, rate limiter, retry, cache, singleflight, metrics
    services/              # ChainIngestionService (orchestrator)
    strategies/            # BaseLiveSourceStrategy + 3 concrete strategies
  feature/                 # FeatureEngine (MarketTickInput → FeatureRowInput)
  scoring/                 # ScoringEngine (FeatureRowInput → ScoreRowInput)
  backtest/                # Engine, optimizer, batch, attribution, gate2 validator, reporting
  shared/
    config/                # 7 domain-specific settings (pydantic-settings, CM_ prefix)
      __init__.py, app.py, postgres.py, infra.py, chain.py,
      ingestion.py, pipeline.py, scanner.py
    db/                    # session.py, repository.py
    schemas/               # Pipeline & backtest Pydantic models
    contracts/             # Events, CandidateSnapshot, FeatureBatch, ScoreBatch
  paper/                   # Placeholder (empty)
  evolution/               # Placeholder (empty)
tests/                     # Flat test directory, no sub-packages
```

## Pipeline stages

`ingestion → feature → scoring → persist` orchestrated by `ChainPipelineService`.

## Quality commands

| Command | What it runs |
|---|---|
| `ruff check src tests` | Lint (E, F, I, UP rules, line-length 100) |
| `ruff format --check src tests` | Format check (not in CI gate but in pre-commit) |
| `pytest -q` | All tests (flat dir, `pythonpath = ["src"]` in pyproject) |
| `mypy src` | Type check (in dev deps, no pyproject config yet — not in CI) |
| `pre-commit run --all-files` | ruff-check, ruff-format, EOF fix, trailing-whitespace, YAML check |

CI gate order: `ruff check → pytest -q` (via `ci-ai-review-repair-gate.ps1`). Always run **lint before test**.

## Testing quirks

- Tests use `fastapi.testclient.TestClient` directly.
- Some tests require Docker services running (PostgreSQL, Redis). Check for `@pytest.mark.skip` patterns.
- Migration tests connect to real DB — skip if no DB available.
- `pytest -q` runs all tests; no markers for unit vs integration.

## Architecture notes

- 4 supported chains: `bsc`, `base`, `eth`, `sol`. Chain IDs are configurable via env.
- Ingestion strategy order (configurable): `dexscreener → geckoterminal → birdeye`.
- Resilience layer is production-grade: circuit breaker, token-bucket rate limiter (per-provider, per-chain), exponential backoff retry, singleflight, LRU cache.
- App enforces per-IP token-bucket rate limiting + optional API key auth middleware.
- Replay API has separate rate limiting and optional API key requirement.
- Alembic migrations use `compare_type=True`. Run `db-revision.ps1` (not `alembic revision`) for new migrations.

## Deployment

- Full stack: `docker compose -f deploy/docker-compose.yml` (app + postgres + clickhouse + redis + minio + prometheus + grafana).
- Lite: `docker compose -f deploy/docker-compose.lite.yml` (app + postgres + redis).
- Dockerfile at `deploy/Dockerfile.app`.
- Backup/restore via `dev.ps1 -Command backup` / `restore`.
