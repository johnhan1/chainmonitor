from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeatureRow(BaseModel):
    chain_id: str
    token_id: str
    ts_minute: datetime
    values: dict[str, float] = Field(default_factory=dict)


class FeatureBatch(BaseModel):
    strategy_version: str
    rows: list[FeatureRow] = Field(default_factory=list)


class ScoreRow(BaseModel):
    chain_id: str
    token_id: str
    ts_minute: datetime
    final_score: float
    conviction: float
    confidence: float


class ScoreBatch(BaseModel):
    strategy_version: str
    rows: list[ScoreRow] = Field(default_factory=list)


class CandidateSnapshot(BaseModel):
    strategy_version: str
    ts_minute: datetime
    chain_id: str
    token_id: str
    tier: str
    rank: int
    reason_codes: list[str] = Field(default_factory=list)

