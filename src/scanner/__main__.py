from __future__ import annotations

import asyncio
import logging
import signal

from src.scanner.cooldown import CooldownManager
from src.scanner.detector import AlphaScorer
from src.scanner.gmgn_client import GmgnClient
from src.scanner.notifier import TelegramNotifier
from src.scanner.orchestrator import ScannerOrchestrator
from src.scanner.snapshot_store import SnapshotStore
from src.shared.config.app import get_app_settings
from src.shared.config.scanner import get_scanner_settings
from src.shared.db.session import get_engine
from src.shared.logging import setup_logging


async def main() -> None:
    app_settings = get_app_settings()
    settings = get_scanner_settings()
    setup_logging(app_settings.log_level)
    logger = logging.getLogger(__name__)

    if not settings.enabled:
        logger.info("Scanner disabled (CM_SCANNER_ENABLED=false)")
        return

    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not bot_token or not chat_id:
        logger.warning("Scanner enabled but TELEGRAM_BOT_TOKEN or CHAT_ID missing")
        return

    # Observability
    from src.scanner.events import STRATEGY_EVENT_TYPES, SYSTEM_EVENT_TYPES, EventBus
    from src.scanner.handlers import (
        DatabaseEventHandler,
        FileEventHandler,
        MetricsHandler,
        StructuredLogHandler,
    )
    from src.scanner.metrics import ScannerMetrics, start_metrics_server

    event_bus = EventBus()
    metrics = ScannerMetrics()
    metrics_handler = MetricsHandler(metrics)

    for et in SYSTEM_EVENT_TYPES:
        event_bus.subscribe(et, metrics_handler)

    log_handler = StructuredLogHandler()
    engine = get_engine()
    db_handler = DatabaseEventHandler(engine=engine)
    file_handler = FileEventHandler()

    for et in STRATEGY_EVENT_TYPES:
        event_bus.subscribe(et, log_handler)
        event_bus.subscribe(et, db_handler)
        event_bus.subscribe(et, file_handler)

    start_metrics_server(settings.metrics_port)
    logger.info("Scanner metrics server started on port %d", settings.metrics_port)

    client = GmgnClient(
        gmgn_cli_path=settings.gmgn_cli_path,
        api_key=settings.gmgn_api_key,
        trending_timeout_seconds=settings.trending_timeout_seconds,
        security_timeout_seconds=settings.security_timeout_seconds,
        rate_limit_per_second=settings.rate_limit_per_second,
        rate_limit_capacity=settings.rate_limit_capacity,
        circuit_failure_threshold=settings.circuit_failure_threshold,
        circuit_recovery_seconds=settings.circuit_recovery_seconds,
        circuit_half_open_max_calls=settings.circuit_half_open_max_calls,
        retry_attempts=settings.retry_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        security_max_concurrency=settings.security_max_concurrency,
    )
    store = SnapshotStore(get_engine())
    scorer = AlphaScorer(
        min_liquidity=settings.min_liquidity,
        max_rug_risk=settings.max_rug_risk,
        max_bundler_rat_ratio=settings.max_bundler_rat_ratio,
        score_high=settings.score_high_threshold,
        score_medium=settings.score_medium_threshold,
        score_low=settings.score_low_threshold,
    )
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    cooldown = CooldownManager(
        cooldown_high_seconds=settings.cooldown_high_seconds,
        cooldown_medium_seconds=settings.cooldown_medium_seconds,
        cooldown_observe_seconds=settings.cooldown_observe_seconds,
    )

    orch = ScannerOrchestrator(
        chains=list(settings.chains),
        client=client,
        store=store,
        scorer=scorer,
        notifier=notifier,
        event_bus=event_bus,
        cooldown=cooldown,
        trending_limit=settings.trending_limit,
        interval_1h_seconds=settings.interval_1h_seconds,
    )

    logger.info(
        "Scanner started chains=%s interval_1m=%ds",
        settings.chains,
        settings.interval_1m_seconds,
    )

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _shutdown() -> None:
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    task = asyncio.create_task(orch.run_forever(interval_seconds=settings.interval_1m_seconds))
    await stop
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Scanner stopped")


if __name__ == "__main__":
    asyncio.run(main())
