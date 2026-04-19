import pytest
from src.ingestion.factory.source_strategy_factory import SourceStrategyFactory
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.ingestion.strategies.mock_source_strategy import MockSourceStrategy
from src.shared.config import Settings, get_settings


def test_settings_parse_chain_token_addresses() -> None:
    settings = Settings(bsc_token_addresses="BNB=0x111,CAKE=0x222")
    mapping = settings.get_chain_token_addresses("bsc")
    assert mapping["BNB"] == "0x111"
    assert mapping["CAKE"] == "0x222"


def test_settings_parse_required_address_symbols() -> None:
    settings = Settings(market_data_required_address_symbols_by_chain="bsc=BNB|CAKE,eth=*")
    assert settings.get_market_data_required_address_symbols("bsc") == {"BNB", "CAKE"}
    assert settings.get_market_data_required_address_symbols("eth") == {
        "ETH",
        "USDC",
        "WBTC",
        "PEPE",
        "UNI",
    }


def test_source_strategy_factory_uses_configured_primary_secondary(monkeypatch) -> None:
    monkeypatch.setenv("CM_INGESTION_PRIMARY_STRATEGY", "mock")
    monkeypatch.setenv("CM_INGESTION_SECONDARY_STRATEGY", "dexscreener")
    get_settings.cache_clear()
    strategy = SourceStrategyFactory.create(chain_id="bsc", data_mode="hybrid")
    assert isinstance(strategy, FallbackSourceChain)
    assert isinstance(strategy.primary, MockSourceStrategy)
    assert isinstance(strategy.secondary, DexScreenerSourceStrategy)
    get_settings.cache_clear()


def test_source_strategy_factory_rejects_invalid_strategy(monkeypatch) -> None:
    monkeypatch.setenv("CM_INGESTION_PRIMARY_STRATEGY", "unknown")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        SourceStrategyFactory.create(chain_id="bsc", data_mode="hybrid")
    get_settings.cache_clear()


def test_source_strategy_factory_rejects_mock_in_production_hybrid(monkeypatch) -> None:
    monkeypatch.setenv("CM_APP_ENV", "prod")
    monkeypatch.setenv("CM_INGESTION_PRIMARY_STRATEGY", "dexscreener")
    monkeypatch.setenv("CM_INGESTION_SECONDARY_STRATEGY", "mock")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="forbidden in production hybrid mode"):
        SourceStrategyFactory.create(chain_id="bsc", data_mode="hybrid")
    get_settings.cache_clear()


def test_source_strategy_factory_allows_mock_in_production_when_explicitly_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CM_APP_ENV", "prod")
    monkeypatch.setenv("CM_INGESTION_PRIMARY_STRATEGY", "dexscreener")
    monkeypatch.setenv("CM_INGESTION_SECONDARY_STRATEGY", "mock")
    monkeypatch.setenv("CM_INGESTION_ALLOW_MOCK_IN_PRODUCTION", "true")
    get_settings.cache_clear()
    strategy = SourceStrategyFactory.create(chain_id="bsc", data_mode="hybrid")
    assert isinstance(strategy, FallbackSourceChain)
    assert isinstance(strategy.secondary, MockSourceStrategy)
    get_settings.cache_clear()
