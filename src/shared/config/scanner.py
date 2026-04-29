from __future__ import annotations

import os
from functools import lru_cache

from pydantic.fields import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class ScannerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_SCANNER_",
        extra="ignore",
    )

    # 是否启用 Scanner 模块
    enabled: bool = True
    # 监控的链列表，逗号分隔
    chains_raw: str = "sol,bsc,base,eth"
    # 代币数量激增判定阈值（单位：新代币数/时间窗口）
    surge_threshold: int = 10
    # 交易量/流动性比率突变的倍数阈值
    spike_ratio: float = 2.0
    # 1 分钟级轮询间隔
    interval_1m_seconds: int = 60
    # 1 小时级趋势扫描间隔
    interval_1h_seconds: int = 300
    # Trending 排行榜取 top N
    trending_limit: int = 50
    # 最低流动性（USD），低于此值不评分
    min_liquidity: float = 50_000.0
    # 最大 Rug Pull 风险分（0~1），超过则排除
    max_rug_risk: float = 0.8
    # 最大捆绑地址比率（0~1），超过则排除
    max_bundler_rat_ratio: float = 0.7
    # AlphaScore 高分阈值（>= 此分 → 高优先级）
    score_high_threshold: int = 75
    # AlphaScore 中分阈值
    score_medium_threshold: int = 65
    # AlphaScore 低分阈值
    score_low_threshold: int = 55
    # 高分代币冷却时间（秒），冷却期内不再重复告警
    cooldown_high_seconds: int = 900
    # 中分代币冷却时间（秒）
    cooldown_medium_seconds: int = 1800
    # 观察中代币冷却时间（秒）
    cooldown_observe_seconds: int = 300
    # Prometheus metrics 监听端口
    metrics_port: int = 9101
    # GMGN API 令牌桶速率（每秒许可数）
    rate_limit_per_second: float = 2.0
    # 令牌桶容量
    rate_limit_capacity: int = 5
    # 断路器：连续失败次数阈值
    circuit_failure_threshold: int = 5
    # 断路器：半开后等待恢复的秒数
    circuit_recovery_seconds: float = 30.0
    # 断路器：半开状态下最大试探请求数
    circuit_half_open_max_calls: int = 2
    # 请求重试次数
    retry_attempts: int = 3
    # 退避初始秒数
    retry_base_seconds: float = 1.0
    # 退避最大秒数
    retry_max_seconds: float = 30.0
    # Trending 榜 API 超时
    trending_timeout_seconds: float = 30.0
    # 安全分析 API 超时
    security_timeout_seconds: float = 15.0
    # 安全分析最大并发数
    security_max_concurrency: int = 5
    # GMGN CLI API 密钥
    gmgn_api_key: str = Field("", validation_alias="CM_GMGN_API_KEY")
    # GMGN CLI 可执行文件路径
    gmgn_cli_path: str = Field("gmgn-cli", validation_alias="CM_GMGN_CLI_PATH")
    # Telegram Bot Token
    telegram_bot_token: str = Field("", validation_alias="CM_TELEGRAM_BOT_TOKEN")
    # 接收告警的 Telegram Chat ID
    telegram_chat_id: str = Field("", validation_alias="CM_TELEGRAM_CHAT_ID")

    @property
    def chains(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.chains_raw.split(",") if item.strip())


@lru_cache
def get_scanner_settings() -> ScannerSettings:
    return ScannerSettings()
