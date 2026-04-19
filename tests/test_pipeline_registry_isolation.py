from src.app.services.pipeline_registry import PipelineComponentRegistry
from src.shared.config import get_settings


def test_registry_returns_fresh_components() -> None:
    chain_id = get_settings().supported_chains[0]
    registry = PipelineComponentRegistry()

    first = registry.resolve(chain_id=chain_id)
    second = registry.resolve(chain_id=chain_id)

    assert first is not second
    assert first.feature_engine is not second.feature_engine
    assert first.scoring_engine is not second.scoring_engine
