from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ChainSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_", extra="ignore")

    bsc_chain_id: str = "bsc"
    bsc_default_symbols: str = "BNB,CAKE,XVS,BUSD,USDT"
    bsc_token_addresses: str = ""
    bsc_strategy_version: str = "bsc-mvp-v1"
    base_chain_id: str = "base"
    base_default_symbols: str = "WETH,USDC,DEGEN,AERO,BRETT"
    base_token_addresses: str = ""
    base_strategy_version: str = "base-mvp-v1"
    eth_chain_id: str = "eth"
    eth_default_symbols: str = "ETH,USDC,WBTC,PEPE,UNI"
    eth_token_addresses: str = ""
    eth_strategy_version: str = "eth-mvp-v1"
    sol_chain_id: str = "sol"
    sol_default_symbols: str = "SOL,USDC,JUP,WIF,BONK"
    sol_token_addresses: str = ""
    sol_strategy_version: str = "sol-mvp-v1"
    ingestion_strategy_order: str = "dexscreener,geckoterminal,birdeye"

    @property
    def supported_chains(self) -> tuple[str, ...]:
        return (
            self.bsc_chain_id,
            self.base_chain_id,
            self.eth_chain_id,
            self.sol_chain_id,
        )

    @property
    def enabled_ingestion_strategies(self) -> tuple[str, ...]:
        raw = self.ingestion_strategy_order.strip().lower()
        if not raw:
            return ()
        requested = [item.strip() for item in raw.split(",") if item.strip()]
        deduped = dict.fromkeys(requested)
        return tuple(deduped.keys())

    def get_chain_symbols(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: self.bsc_default_symbols,
            self.base_chain_id: self.base_default_symbols,
            self.eth_chain_id: self.eth_default_symbols,
            self.sol_chain_id: self.sol_default_symbols,
        }
        return mapping[chain_id]

    def get_strategy_version(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: self.bsc_strategy_version,
            self.base_chain_id: self.base_strategy_version,
            self.eth_chain_id: self.eth_strategy_version,
            self.sol_chain_id: self.sol_strategy_version,
        }
        return mapping[chain_id]

    def get_dexscreener_chain_id(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "ethereum",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]

    def get_chain_token_addresses(self, chain_id: str) -> dict[str, str]:
        mapping = {
            self.bsc_chain_id: self.bsc_token_addresses,
            self.base_chain_id: self.base_token_addresses,
            self.eth_chain_id: self.eth_token_addresses,
            self.sol_chain_id: self.sol_token_addresses,
        }
        raw = mapping[chain_id].strip()
        if not raw:
            return {}
        pairs = [item.strip() for item in raw.split(",") if item.strip()]
        parsed: dict[str, str] = {}
        for pair in pairs:
            if "=" not in pair:
                continue
            symbol, address = pair.split("=", 1)
            symbol = symbol.strip().upper()
            address = address.strip()
            if symbol and address:
                parsed[symbol] = address
        return parsed

    def get_geckoterminal_network(self, chain_id: str) -> str:
        from src.shared.config.ingestion import get_ingestion_settings

        ingestion = get_ingestion_settings()
        parsed = ingestion._parse_chain_override(overrides=ingestion.geckoterminal_network_by_chain)
        override = parsed.get(chain_id)
        if override:
            return override
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "eth",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]

    def get_birdeye_chain(self, chain_id: str) -> str:
        from src.shared.config.ingestion import get_ingestion_settings

        ingestion = get_ingestion_settings()
        parsed = ingestion._parse_chain_override(overrides=ingestion.birdeye_chain_by_chain)
        override = parsed.get(chain_id)
        if override:
            return override
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "ethereum",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]


@lru_cache
def get_chain_settings() -> ChainSettings:
    return ChainSettings()
