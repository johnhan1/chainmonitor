from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.feature.feature_engine import FeatureEngine
from src.scoring.scoring_engine import ScoringEngine
from src.shared.config import get_settings
from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput, ScoreRowInput


class FeatureEngineProtocol(Protocol):
    def build_features(self, ticks: list[MarketTickInput]) -> list[FeatureRowInput]: ...


class ScoringEngineProtocol(Protocol):
    def score(
        self,
        ticks: list[MarketTickInput],
        features: list[FeatureRowInput],
        strategy_version: str | None = None,
    ) -> list[ScoreRowInput]: ...


@dataclass(frozen=True)
class PipelineComponents:
    feature_engine: FeatureEngineProtocol
    scoring_engine: ScoringEngineProtocol


class PipelineComponentRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._supported_chains = set(self.settings.supported_chains)

    def resolve(self, chain_id: str) -> PipelineComponents:
        if chain_id not in self._supported_chains:
            raise ValueError(f"unsupported chain_id: {chain_id}")
        return PipelineComponents(
            feature_engine=FeatureEngine(),
            scoring_engine=ScoringEngine(),
        )
