from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.app import main
from src.shared.schemas.pipeline import PipelineRunSummary


class _FakePipelineService:
    async def replay(self, ts_minute: datetime) -> PipelineRunSummary:
        return PipelineRunSummary(
            run_id="testreplay123456",
            chain_id="bsc",
            strategy_version="bsc-mvp-v1",
            ts_minute=ts_minute,
            tick_count=1,
            candidate_count=1,
            status="success",
            trigger="replay",
            skipped=False,
        )


def _reset_replay_buckets() -> None:
    main._REPLAY_RL_BUCKET.clear()
    main._REPLAY_RL_LAST_SEEN.clear()
    main._REPLAY_RL_LAST_SWEEP_AT = 0.0


def test_replay_allowlist_rejects_chain(monkeypatch) -> None:
    monkeypatch.setattr(main.pipeline_settings, "replay_chain_allowlist", "bsc")
    monkeypatch.setattr(main.pipeline_settings, "replay_require_api_key", False)
    monkeypatch.setattr(main, "_get_pipeline_service", lambda chain_id: _FakePipelineService())
    _reset_replay_buckets()
    client = TestClient(main.app)
    response = client.post("/pipeline/eth/replay", params={"ts_minute": "2026-01-01T00:00:00Z"})
    assert response.status_code == 403
    payload = response.json()["detail"]
    assert payload["message"] == "eth replay is disabled"
    assert payload["trace_id"]


def test_replay_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(main.pipeline_settings, "replay_chain_allowlist", "bsc")
    monkeypatch.setattr(main.pipeline_settings, "replay_require_api_key", True)
    monkeypatch.setattr(main.app_settings, "api_key", "secret")
    monkeypatch.setattr(main, "_get_pipeline_service", lambda chain_id: _FakePipelineService())
    _reset_replay_buckets()
    client = TestClient(main.app)
    response = client.post("/pipeline/bsc/replay", params={"ts_minute": "2026-01-01T00:00:00Z"})
    assert response.status_code == 401
    payload = response.json()["detail"]
    assert payload["message"] == "unauthorized replay request"
    assert payload["trace_id"]


def test_replay_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(main.pipeline_settings, "replay_chain_allowlist", "bsc")
    monkeypatch.setattr(main.pipeline_settings, "replay_require_api_key", False)
    monkeypatch.setattr(main.pipeline_settings, "replay_rate_limit_per_minute", 1)
    monkeypatch.setattr(main.pipeline_settings, "replay_rate_limit_burst", 0)
    monkeypatch.setattr(main, "_get_pipeline_service", lambda chain_id: _FakePipelineService())
    _reset_replay_buckets()
    client = TestClient(main.app)

    first = client.post(
        "/pipeline/bsc/replay", params={"ts_minute": datetime.now(tz=UTC).isoformat()}
    )
    assert first.status_code == 200
    second = client.post(
        "/pipeline/bsc/replay", params={"ts_minute": datetime.now(tz=UTC).isoformat()}
    )
    assert second.status_code == 429
    payload = second.json()["detail"]
    assert payload["message"] == "replay rate limit exceeded"
    assert payload["trace_id"]
