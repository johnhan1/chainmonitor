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
from src.shared.config import get_settings
from src.shared.db.session import get_engine
from src.shared.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.app_log_level)
    logger = logging.getLogger(__name__)

    if not settings.scanner_enabled:
        logger.info("Scanner disabled (CM_SCANNER_ENABLED=false)")
        return

    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not bot_token or not chat_id:
        logger.warning("Scanner enabled but TELEGRAM_BOT_TOKEN or CHAT_ID missing")
        return

    # Observability
    from src.scanner.events import EVENT_TYPES, EventBus
    from src.scanner.handlers import MetricsHandler, StructuredLogHandler
    from src.scanner.metrics import ScannerMetrics, start_metrics_server

    event_bus = EventBus()
    log_handler = StructuredLogHandler()
    metrics_handler = MetricsHandler(ScannerMetrics())
    for et in EVENT_TYPES:
        event_bus.subscribe(et, log_handler)
        event_bus.subscribe(et, metrics_handler)

    start_metrics_server(settings.scanner_metrics_port)
    logger.info("Scanner metrics server started on port %d", settings.scanner_metrics_port)

    client = GmgnClient(
        gmgn_cli_path=settings.gmgn_cli_path,
        api_key=settings.gmgn_api_key,
    )
    store = SnapshotStore(get_engine())
    scorer = AlphaScorer(
        min_liquidity=settings.scanner_min_liquidity,
        max_rug_risk=settings.scanner_max_rug_risk,
        max_bundler_rat_ratio=settings.scanner_max_bundler_rat_ratio,
        score_high=settings.scanner_score_high_threshold,
        score_medium=settings.scanner_score_medium_threshold,
        score_low=settings.scanner_score_low_threshold,
    )
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    cooldown = CooldownManager(
        cooldown_high_seconds=settings.scanner_cooldown_high_seconds,
        cooldown_medium_seconds=settings.scanner_cooldown_medium_seconds,
        cooldown_observe_seconds=settings.scanner_cooldown_observe_seconds,
    )

    orch = ScannerOrchestrator(
        chains=list(settings.scanner_chains),
        client=client,
        store=store,
        scorer=scorer,
        notifier=notifier,
        event_bus=event_bus,
        cooldown=cooldown,
        trending_limit=settings.scanner_trending_limit,
        interval_1h_seconds=settings.scanner_interval_1h_seconds,
    )

    logger.info(
        "Scanner started chains=%s interval_1m=%ds",
        settings.scanner_chains,
        settings.scanner_interval_1m_seconds,
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

    task = asyncio.create_task(
        orch.run_forever(interval_seconds=settings.scanner_interval_1m_seconds)
    )
    await stop
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Scanner stopped")


if __name__ == "__main__":
    asyncio.run(main())
