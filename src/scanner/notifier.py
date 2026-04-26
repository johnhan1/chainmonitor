from __future__ import annotations

import logging

import httpx
from src.scanner.models import AnomalyEvent, AnomalyType

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self, bot_token: str, chat_id: str, api_base: str = "https://api.telegram.org"
    ) -> None:
        self._base_url = f"{api_base}/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    async def send_anomalies(self, chain: str, interval: str, events: list[AnomalyEvent]) -> None:
        if not events:
            return
        text = self._format_message(chain, interval, events)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    self._base_url,
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "MarkdownV2"},
                )
                if resp.status_code == 400:
                    logger.error("TG 400 body: %s", resp.text[:500])
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("TG send failed: %s", e)

    def _format_message(self, chain: str, interval: str, events: list[AnomalyEvent]) -> str:
        lines: list[str] = [
            f"\U0001f525 *{chain.upper()} {interval} \u5f02\u52a8*",
            "",
        ]
        for e in events:
            t = e.token
            sym = _escape(t.symbol)
            addr = _escape(f"{t.address[:6]}\u2026{t.address[-4:]}")
            price = _escape(f"${t.price_usd:.4f}" if t.price_usd < 1 else f"${t.price_usd:.2f}")
            vol = _escape(_fmt_usd(t.volume_1m)) if t.volume_1m else "N/A"
            mc = _escape(_fmt_usd(t.market_cap)) if t.market_cap else "N/A"
            smart = str(t.smart_degen_count) if t.smart_degen_count is not None else "N/A"

            if e.type == AnomalyType.NEW:
                lines.append(f"\U0001f195 *NEW* \\-\\- `{sym}`")
                lines.append(f"  \u5730\u5740: `{addr}`")
                lines.append(f"  \u4ef7\u683c: {price}")
                lines.append(f"  \u6210\u4ea4\u989d({interval}): {vol}")
                lines.append(f"  \u806a\u660e\u94b1: {smart}")
                lines.append(f"  \u5e02\u503c: {mc}")
            elif e.type == AnomalyType.SURGE:
                old = str(e.previous_rank) if e.previous_rank is not None else "?"
                chg = str(e.rank_change) if e.rank_change is not None else "?"
                lines.append(
                    f"\u2b06\ufe0f *SURGE* \\-\\- `{sym}` \\(#{old} \u2192 #{t.rank}, +{chg}\\)"
                )
                lines.append(f"  \u6210\u4ea4\u989d({interval}): {vol}")
            elif e.type == AnomalyType.SPIKE:
                lines.append(f"\U0001f525 *SPIKE* \\-\\- `{sym}` \\({e.reason}\\)")
                lines.append(f"  \u6210\u4ea4\u989d({interval}): {vol}")
            lines.append("")

        return "\n".join(lines).strip()


def _escape(text: str) -> str:
    chars = "_*[]()~`>#+-=|{}.!"
    for c in chars:
        text = text.replace(c, f"\\{c}")
    return text


def _fmt_usd(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.2f}"
