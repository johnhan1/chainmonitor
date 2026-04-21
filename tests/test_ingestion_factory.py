import pytest
from src.ingestion.factory.source_strategy_factory import SourceStrategyFactory
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.birdeye_source_strategy import BirdeyeSourceStrategy
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.ingestion.strategies.geckoterminal_source_strategy import GeckoTerminalSourceStrategy
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


def test_settings_get_geckoterminal_network() -> None:
    settings = Settings(market_data_geckoterminal_network_by_chain="bsc=bnb-smart-chain")
    assert settings.get_geckoterminal_network("bsc") == "bnb-smart-chain"
    assert settings.get_geckoterminal_network("eth") == "eth"


def test_settings_get_birdeye_chain() -> None:
    settings = Settings(market_data_birdeye_chain_by_chain="bsc=bsc-mainnet")
    assert settings.get_birdeye_chain("bsc") == "bsc-mainnet"
    assert settings.get_birdeye_chain("eth") == "ethereum"


def test_source_strategy_factory_uses_configured_strategy_order(monkeypatch) -> None:
    monkeypatch.setenv("CM_INGESTION_STRATEGY_ORDER", "dexscreener,geckoterminal,birdeye")
    get_settings.cache_clear()
    strategy = SourceStrategyFactory.create(chain_id="bsc")
    assert isinstance(strategy, FallbackSourceChain)
    assert len(strategy.sources) == 3
    assert isinstance(strategy.sources[0], DexScreenerSourceStrategy)
    assert isinstance(strategy.sources[1], GeckoTerminalSourceStrategy)
    assert isinstance(strategy.sources[2], BirdeyeSourceStrategy)
    get_settings.cache_clear()


def test_source_strategy_factory_supports_geckoterminal(monkeypatch) -> None:
    monkeypatch.setenv("CM_INGESTION_STRATEGY_ORDER", "geckoterminal,dexscreener,birdeye")
    get_settings.cache_clear()
    strategy = SourceStrategyFactory.create(chain_id="bsc")
    assert isinstance(strategy, FallbackSourceChain)
    assert isinstance(strategy.sources[0], GeckoTerminalSourceStrategy)
    assert isinstance(strategy.sources[1], DexScreenerSourceStrategy)
    assert isinstance(strategy.sources[2], BirdeyeSourceStrategy)
    get_settings.cache_clear()


def test_source_strategy_factory_rejects_invalid_strategy(monkeypatch) -> None:
    monkeypatch.setenv("CM_INGESTION_STRATEGY_ORDER", "unknown,dexscreener")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        SourceStrategyFactory.create(chain_id="bsc")
    get_settings.cache_clear()
