from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class ChainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_",
        extra="ignore",
    )

    # BSC 链标识
    bsc_chain_id: str = "bsc"
    # BSC 默认监控代币列表，逗号分隔
    bsc_default_symbols: str = "BNB,CAKE,XVS,BUSD,USDT"
    # BSC 代币地址映射，格式: SYMBOL=address,SYMBOL=address
    bsc_token_addresses: str = ""
    # BSC 策略版本
    bsc_strategy_version: str = "bsc-mvp-v1"
    # Base 链标识
    base_chain_id: str = "base"
    # Base 默认监控代币列表
    base_default_symbols: str = "WETH,USDC,DEGEN,AERO,BRETT"
    # Base 代币地址映射
    base_token_addresses: str = ""
    # Base 策略版本
    base_strategy_version: str = "base-mvp-v1"
    # Ethereum 链标识
    eth_chain_id: str = "eth"
    # Ethereum 默认监控代币列表
    eth_default_symbols: str = "ETH,USDC,WBTC,PEPE,UNI"
    # Ethereum 代币地址映射
    eth_token_addresses: str = ""
    # Ethereum 策略版本
    eth_strategy_version: str = "eth-mvp-v1"
    # Solana 链标识
    sol_chain_id: str = "sol"
    # Solana 默认监控代币列表
    sol_default_symbols: str = "SOL,USDC,JUP,WIF,BONK"
    # Solana 代币地址映射
    sol_token_addresses: str = ""
    # Solana 策略版本
    sol_strategy_version: str = "sol-mvp-v1"
    # 数据源策略优先级顺序，逗号分隔（第一个为主数据源）
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
