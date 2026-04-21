import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from src.app.services.chain_pipeline_service import ChainPipelineService
from src.app.services.chain_scheduler import ChainPipelineScheduler
from src.backtest.service import BacktestService
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.factory.source_strategy_factory import SourceStrategyFactory
from src.shared.config import get_settings
from src.shared.db import close_engine
from src.shared.logging import setup_logging
from src.shared.schemas.backtest import BacktestConfig
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)
settings = get_settings()
SourceStrategyFactory.validate_settings(settings)
setup_logging(settings.app_log_level)
REQUEST_COUNT = Counter("cm_http_requests_total", "Total HTTP requests", ["path", "method"])
RATE_LIMIT_REJECTS = Counter(
    "cm_http_rate_limit_rejects_total", "Total HTTP rate-limit rejects", ["path"]
)
AUTH_REJECTS = Counter("cm_http_auth_rejects_total", "Total HTTP auth rejects", ["path"])
REPLAY_RATE_LIMIT_REJECTS = Counter(
    "cm_http_replay_rate_limit_rejects_total",
    "Total replay API rate-limit rejects",
    ["chain_id"],
)

pipeline_services: dict[str, ChainPipelineService] = {}
backtest_services: dict[str, BacktestService] = {}
scheduler_chain_ids = settings.enabled_scheduler_chains
schedulers: dict[str, ChainPipelineScheduler] = {}

_RL_BUCKET: dict[str, deque[float]] = {}
_RL_LAST_SEEN: dict[str, float] = {}
_RL_LAST_SWEEP_AT = 0.0
_RL_SWEEP_INTERVAL_SECONDS = 30.0
_REPLAY_RL_BUCKET: dict[str, deque[float]] = {}
_REPLAY_RL_LAST_SEEN: dict[str, float] = {}
_REPLAY_RL_LAST_SWEEP_AT = 0.0
_PUBLIC_PATHS = {"/healthz", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _log_runtime_config_snapshot() -> None:
    for chain_id in settings.supported_chains:
        logger.info(
            "runtime config chain_id=%s scheduler_enabled=%s scheduler_interval=%s scheduler_jitter=%s retry=%s concurrency=%s rate=%.3f circuit_threshold=%s circuit_recovery=%.3f min_success_ratio=%.3f min_pair_age=%s",  # noqa: E501
            chain_id,
            settings.pipeline_scheduler_enabled,
            settings.pipeline_scheduler_interval_seconds,
            settings.pipeline_scheduler_startup_jitter_seconds,
            settings.get_market_data_retry_attempts(chain_id=chain_id),
            settings.get_market_data_max_concurrency(chain_id=chain_id),
            settings.get_market_data_rate_limit_per_second(chain_id=chain_id),
            settings.get_market_data_circuit_failure_threshold(chain_id=chain_id),
            settings.get_market_data_circuit_recovery_seconds(chain_id=chain_id),
            settings.get_market_data_min_success_ratio(chain_id=chain_id),
            settings.get_market_data_min_pair_age_seconds(chain_id=chain_id),
        )


_log_runtime_config_snapshot()


def _trace_id() -> str:
    return uuid4().hex[:16]


def _http_error(
    *,
    status_code: int,
    message: str,
    trace_id: str | None = None,
    exc: Exception | None = None,
) -> HTTPException:
    resolved_trace_id = trace_id or _trace_id()
    if exc is None:
        logger.error("request failed trace_id=%s message=%s", resolved_trace_id, message)
    else:
        logger.exception(
            "request failed trace_id=%s message=%s",
            resolved_trace_id,
            message,
            exc_info=exc,
        )
    return HTTPException(
        status_code=status_code,
        detail={"message": message, "trace_id": resolved_trace_id},
    )


def _sweep_rate_limit_bucket(now: float) -> None:
    ttl_seconds = max(60.0, settings.app_rate_limit_bucket_key_ttl_seconds)
    stale_before = now - ttl_seconds
    stale_keys = [key for key, last_seen in _RL_LAST_SEEN.items() if last_seen < stale_before]
    for key in stale_keys:
        _RL_LAST_SEEN.pop(key, None)
        _RL_BUCKET.pop(key, None)

    max_keys = max(1, settings.app_rate_limit_bucket_max_keys)
    if len(_RL_LAST_SEEN) <= max_keys:
        return

    overflow = len(_RL_LAST_SEEN) - max_keys
    oldest_keys = sorted(_RL_LAST_SEEN.items(), key=lambda item: item[1])[:overflow]
    for key, _ in oldest_keys:
        _RL_LAST_SEEN.pop(key, None)
        _RL_BUCKET.pop(key, None)


def _enforce_replay_request(request: Request, chain_id: str) -> None:
    global _REPLAY_RL_LAST_SWEEP_AT
    if chain_id not in settings.replay_allowed_chains:
        raise _http_error(
            status_code=status.HTTP_403_FORBIDDEN,
            message=f"{chain_id} replay is disabled",
        )

    if settings.pipeline_replay_require_api_key:
        expected = settings.app_api_key.strip()
        provided = request.headers.get("x-api-key", "")
        if not expected:
            raise _http_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message="replay api key is not configured",
            )
        if provided != expected:
            AUTH_REJECTS.labels(path="/pipeline/{chain_id}/replay").inc()
            raise _http_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="unauthorized replay request",
            )

    limit_base = max(0, settings.pipeline_replay_rate_limit_per_minute)
    if limit_base <= 0:
        return

    now = monotonic()
    if now - _REPLAY_RL_LAST_SWEEP_AT >= _RL_SWEEP_INTERVAL_SECONDS:
        ttl_seconds = max(60.0, settings.app_rate_limit_bucket_key_ttl_seconds)
        stale_before = now - ttl_seconds
        stale_keys = [
            key for key, last_seen in _REPLAY_RL_LAST_SEEN.items() if last_seen < stale_before
        ]
        for key in stale_keys:
            _REPLAY_RL_LAST_SEEN.pop(key, None)
            _REPLAY_RL_BUCKET.pop(key, None)
        _REPLAY_RL_LAST_SWEEP_AT = now

    source_ip = request.client.host if request.client else "unknown"
    key = f"{source_ip}:{chain_id}"
    timestamps = _REPLAY_RL_BUCKET.setdefault(key, deque())
    _REPLAY_RL_LAST_SEEN[key] = now
    cutoff = now - 60.0
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()
    replay_limit = max(1, limit_base + settings.pipeline_replay_rate_limit_burst)
    if len(timestamps) >= replay_limit:
        REPLAY_RATE_LIMIT_REJECTS.labels(chain_id=chain_id).inc()
        raise _http_error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message="replay rate limit exceeded",
        )
    timestamps.append(now)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.pipeline_scheduler_enabled:
        for chain_id in scheduler_chain_ids:
            try:
                pipeline = _get_pipeline_service(chain_id=chain_id)
                scheduler = ChainPipelineScheduler(
                    chain_id=chain_id,
                    pipeline=pipeline,
                    interval_seconds=settings.pipeline_scheduler_interval_seconds,
                    initial_delay_seconds=settings.pipeline_scheduler_initial_delay_seconds,
                    startup_jitter_seconds=settings.pipeline_scheduler_startup_jitter_seconds,
                )
                await scheduler.start()
                schedulers[chain_id] = scheduler
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler startup failed chain_id=%s: %s", chain_id, exc)
    try:
        yield
    finally:
        if settings.pipeline_scheduler_enabled:
            for scheduler in schedulers.values():
                await scheduler.stop()
            schedulers.clear()
        for service in pipeline_services.values():
            await service.aclose()
        pipeline_services.clear()
        backtest_services.clear()
        close_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


def _auth_required(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return False
    if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
        return False
    return True


@app.middleware("http")
async def auth_and_rate_limit_middleware(request: Request, call_next):
    global _RL_LAST_SWEEP_AT
    request_id = request.headers.get("x-request-id", uuid4().hex[:16])
    if settings.app_require_api_key and _auth_required(request.url.path):
        expected = settings.app_api_key.strip()
        provided = request.headers.get("x-api-key", "")
        if not expected or provided != expected:
            AUTH_REJECTS.labels(path=request.url.path).inc()
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

    if settings.app_rate_limit_per_minute > 0:
        now = monotonic()
        if now - _RL_LAST_SWEEP_AT >= _RL_SWEEP_INTERVAL_SECONDS:
            _sweep_rate_limit_bucket(now)
            _RL_LAST_SWEEP_AT = now
        window_seconds = 60.0
        source_ip = request.client.host if request.client else "unknown"
        key = f"{source_ip}:{request.url.path}"
        timestamps = _RL_BUCKET.setdefault(key, deque())
        _RL_LAST_SEEN[key] = now
        cutoff = now - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        limit = max(1, settings.app_rate_limit_per_minute + settings.app_rate_limit_burst)
        if len(timestamps) >= limit:
            RATE_LIMIT_REJECTS.labels(path=request.url.path).inc()
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        timestamps.append(now)
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


def _get_pipeline_service(chain_id: str) -> ChainPipelineService:
    if chain_id not in settings.supported_chains:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported chain_id '{chain_id}', supported={settings.supported_chains}",
        )
    service = pipeline_services.get(chain_id)
    if service is None:
        service = ChainPipelineService(chain_id=chain_id)
        pipeline_services[chain_id] = service
    return service


def _get_backtest_service(chain_id: str) -> BacktestService:
    if chain_id not in settings.supported_chains:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported chain_id '{chain_id}', supported={settings.supported_chains}",
        )
    service = backtest_services.get(chain_id)
    if service is None:
        service = BacktestService(chain_id=chain_id)
        backtest_services[chain_id] = service
    return service


@app.get("/healthz", tags=["infra"])
def healthz() -> dict[str, str]:
    REQUEST_COUNT.labels(path="/healthz", method="GET").inc()
    return {"status": "ok", "env": settings.app_env}


@app.get("/metrics", tags=["infra"])
def metrics() -> Response:
    REQUEST_COUNT.labels(path="/metrics", method="GET").inc()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/pipeline/{chain_id}/run-once", tags=["pipeline"])
async def chain_run_once(chain_id: str) -> dict:
    REQUEST_COUNT.labels(path="/pipeline/{chain_id}/run-once", method="POST").inc()
    service = _get_pipeline_service(chain_id=chain_id)
    try:
        summary = await service.run_once(trigger="manual")
        return summary.model_dump()
    except IngestionFetchError as exc:
        raise _http_error(
            status_code=502,
            message=f"{chain_id} ingestion failed",
            trace_id=exc.trace_id,
            exc=exc,
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} pipeline run failed", exc=exc
        ) from exc


@app.get("/pipeline/{chain_id}/candidates", tags=["pipeline"])
def chain_candidates(
    chain_id: str,
    tier: str | None = Query(default=None, pattern="^(A|B|C)?$"),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[dict]:
    REQUEST_COUNT.labels(path="/pipeline/{chain_id}/candidates", method="GET").inc()
    service = _get_pipeline_service(chain_id=chain_id)
    try:
        return service.get_latest_candidates(tier=tier, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} candidates query failed", exc=exc
        ) from exc


@app.post("/pipeline/{chain_id}/replay", tags=["pipeline"])
async def chain_replay(
    chain_id: str,
    request: Request,
    ts_minute: str = Query(..., description="ISO8601 UTC timestamp"),
) -> dict:
    REQUEST_COUNT.labels(path="/pipeline/{chain_id}/replay", method="POST").inc()
    _enforce_replay_request(request=request, chain_id=chain_id)
    service = _get_pipeline_service(chain_id=chain_id)
    try:
        replay_ts = ts_minute.replace("Z", "+00:00")
        summary = await service.replay(ts_minute=datetime.fromisoformat(replay_ts))
        return summary.model_dump()
    except IngestionFetchError as exc:
        raise _http_error(
            status_code=502,
            message=f"{chain_id} ingestion failed",
            trace_id=exc.trace_id,
            exc=exc,
        ) from exc
    except ValueError as exc:
        raise _http_error(
            status_code=400, message=f"{chain_id} replay request invalid", exc=exc
        ) from exc
    except RuntimeError as exc:
        raise _http_error(status_code=429, message=f"{chain_id} replay rejected", exc=exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _http_error(status_code=500, message=f"{chain_id} replay failed", exc=exc) from exc


@app.get("/pipeline/{chain_id}/runs", tags=["pipeline"])
def chain_runs(chain_id: str, limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    REQUEST_COUNT.labels(path="/pipeline/{chain_id}/runs", method="GET").inc()
    service = _get_pipeline_service(chain_id=chain_id)
    try:
        return service.get_recent_runs(limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} runs query failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/run", tags=["backtest"])
async def run_backtest(chain_id: str, config: BacktestConfig | None = None) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/run", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = config
        if normalized is not None:
            normalized.chain_id = chain_id
        report = await service.run_backtest(config=normalized)
        return report.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} backtest run failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/gate2-check", tags=["backtest"])
async def run_backtest_gate2_check(chain_id: str, config: BacktestConfig | None = None) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/gate2-check", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = config
        if normalized is not None:
            normalized.chain_id = chain_id
        report = await service.run_gate2_check(config=normalized)
        if not report.gate2 or not report.gate2.passed:
            raise HTTPException(
                status_code=422,
                detail={"message": "gate2 check failed", "result": report.model_dump()},
            )
        return report.model_dump()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} gate2 check failed", exc=exc
        ) from exc


@app.get("/backtest/{chain_id}/runs", tags=["backtest"])
def list_backtest_runs(chain_id: str, limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/runs", method="GET").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        return service.list_recent_backtests(limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} backtest runs query failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/optimize", tags=["backtest"])
async def optimize_backtest(chain_id: str, config: BacktestConfig | None = None) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/optimize", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = config
        if normalized is not None:
            normalized.chain_id = chain_id
        report = await service.optimize_parameters(config=normalized)
        return report.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} parameter optimize failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/attribution", tags=["backtest"])
async def backtest_attribution(chain_id: str, config: BacktestConfig | None = None) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/attribution", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = config
        if normalized is not None:
            normalized.chain_id = chain_id
        report = await service.build_attribution(config=normalized)
        return report.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} attribution failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/report", tags=["backtest"])
async def export_backtest_report(chain_id: str, config: BacktestConfig | None = None) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/report", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = config
        if normalized is not None:
            normalized.chain_id = chain_id
        return await service.export_backtest_report(config=normalized)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} report export failed", exc=exc
        ) from exc


@app.post("/backtest/{chain_id}/batch/run", tags=["backtest"])
async def run_batch_backtest(
    chain_id: str,
    configs: list[BacktestConfig],
    gate2_required: bool = Query(default=False),
) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/batch/run", method="POST").inc()
    service = _get_backtest_service(chain_id=chain_id)
    try:
        normalized = [config.model_copy(update={"chain_id": chain_id}) for config in configs]
        result = await service.run_batch_backtest(configs=normalized, gate2_required=gate2_required)
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(
            status_code=500, message=f"{chain_id} batch backtest failed", exc=exc
        ) from exc


@app.get("/backtest/{chain_id}/batch/{job_id}", tags=["backtest"])
def get_batch_backtest_job(chain_id: str, job_id: str) -> dict:
    REQUEST_COUNT.labels(path="/backtest/{chain_id}/batch/{job_id}", method="GET").inc()
    service = _get_backtest_service(chain_id=chain_id)
    job = service.get_batch_job(job_id=job_id)
    if job is None or job.chain_id != chain_id:
        raise HTTPException(status_code=404, detail=f"batch job not found: {job_id}")
    return job.model_dump()
