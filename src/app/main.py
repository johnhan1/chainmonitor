from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException, Query
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from src.app.services.bsc_pipeline import BscPipelineService
from src.app.services.bsc_scheduler import BscPipelineScheduler
from src.shared.config import get_settings
from src.shared.logging import setup_logging
from starlette.responses import Response

settings = get_settings()
setup_logging(settings.app_log_level)
REQUEST_COUNT = Counter("cm_http_requests_total", "Total HTTP requests", ["path", "method"])
bsc_pipeline_service = BscPipelineService()
bsc_scheduler = BscPipelineScheduler(pipeline=bsc_pipeline_service)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.bsc_scheduler_enabled:
        await bsc_scheduler.start()
    try:
        yield
    finally:
        if settings.bsc_scheduler_enabled:
            await bsc_scheduler.stop()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["infra"])
def healthz() -> dict[str, str]:
    REQUEST_COUNT.labels(path="/healthz", method="GET").inc()
    return {"status": "ok", "env": settings.app_env}


@app.get("/metrics", tags=["infra"])
def metrics() -> Response:
    REQUEST_COUNT.labels(path="/metrics", method="GET").inc()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/pipeline/bsc/run-once", tags=["pipeline"])
def bsc_run_once() -> dict:
    REQUEST_COUNT.labels(path="/pipeline/bsc/run-once", method="POST").inc()
    try:
        summary = bsc_pipeline_service.run_once(trigger="manual")
        return summary.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"bsc pipeline run failed: {exc}") from exc


@app.get("/pipeline/bsc/candidates", tags=["pipeline"])
def bsc_candidates(
    tier: str | None = Query(default=None, pattern="^(A|B|C)?$"),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[dict]:
    REQUEST_COUNT.labels(path="/pipeline/bsc/candidates", method="GET").inc()
    try:
        return bsc_pipeline_service.get_latest_candidates(tier=tier, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"bsc candidates query failed: {exc}") from exc


@app.post("/pipeline/bsc/replay", tags=["pipeline"])
def bsc_replay(ts_minute: str = Query(..., description="ISO8601 UTC timestamp")) -> dict:
    REQUEST_COUNT.labels(path="/pipeline/bsc/replay", method="POST").inc()
    try:
        replay_ts = ts_minute.replace("Z", "+00:00")
        summary = bsc_pipeline_service.replay(ts_minute=datetime.fromisoformat(replay_ts))
        return summary.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"bsc replay failed: {exc}") from exc


@app.get("/pipeline/bsc/runs", tags=["pipeline"])
def bsc_runs(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    REQUEST_COUNT.labels(path="/pipeline/bsc/runs", method="GET").inc()
    try:
        return bsc_pipeline_service.get_recent_runs(limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"bsc runs query failed: {exc}") from exc

