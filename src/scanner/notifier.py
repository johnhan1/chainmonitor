from __future__ import annotations

import logging

import httpx
from src.scanner.models import AlphaSignal, AnomalyEvent, AnomalyType

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        api_base: str = "https://api.telegram.org",
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
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("TG send failed: %s", e)

    def _format_message(self, chain: str, interval: str, events: list[AnomalyEvent]) -> str:
        lines: list[str] = [
            f"🔥 <b>{chain.upper()} {interval} 异动</b>",
            "",
        ]
        for e in events:
            t = e.token
            sym = _html_escape(t.symbol)
            addr = _html_escape(f"{t.address[:6]}…{t.address[-4:]}")
            price = _html_escape(
                f"${t.price_usd:.4f}" if t.price_usd < 1 else f"${t.price_usd:.2f}"
            )
            vol = _html_escape(_fmt_usd(t.volume_1m)) if t.volume_1m else "N/A"
            mc = _html_escape(_fmt_usd(t.market_cap)) if t.market_cap else "N/A"
            smart = str(t.smart_degen_count) if t.smart_degen_count is not None else "N/A"

            if e.type == AnomalyType.NEW:
                lines.append(f"🆕 <b>NEW</b> -- <code>{sym}</code>")
                lines.append(f"  地址: <code>{addr}</code>")
                lines.append(f"  价格: {price}")
                lines.append(f"  成交额({interval}): {vol}")
                lines.append(f"  聪明钱: {smart}")
                lines.append(f"  市值: {mc}")
            elif e.type == AnomalyType.SURGE:
                old = str(e.previous_rank) if e.previous_rank is not None else "?"
                chg = str(e.rank_change) if e.rank_change is not None else "?"
                lines.append(f"⬆️ <b>SURGE</b> -- <code>{sym}</code> (#{old} → #{t.rank}, +{chg})")
                lines.append(f"  成交额({interval}): {vol}")
            elif e.type == AnomalyType.SPIKE:
                lines.append(f"🔥 <b>SPIKE</b> -- <code>{sym}</code> ({e.reason})")
                lines.append(f"  成交额({interval}): {vol}")
            lines.append("")

        return "\n".join(lines).strip()

    async def send_alpha(self, signal: AlphaSignal) -> None:
        text = self._format_alpha(signal)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    self._base_url,
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("TG send failed: %s", e)

    def _format_alpha(self, sig: AlphaSignal) -> str:
        t = sig.token.token
        bd = sig.token.breakdown
        level_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "OBSERVE": "🔵"}.get(sig.level, "⚪")
        sym = _html_escape(t.symbol)
        addr = _html_escape(f"{t.address[:6]}…{t.address[-4:]}")
        price = _html_escape(f"${t.price_usd:.4f}" if t.price_usd < 1 else f"${t.price_usd:.2f}")
        vol = _html_escape(_fmt_usd(t.volume_1m)) if t.volume_1m else "N/A"
        mc = _html_escape(_fmt_usd(t.market_cap)) if t.market_cap else "N/A"

        lines = [
            (
                f"{level_icon} <b>[{sig.token.score}]"
                f" {sig.chain.upper()} {sig.interval}</b> — <code>{sym}</code>"
            ),
            "",
            "<b>📊 评分明细</b>",
            f"  聪明钱领先: {bd.get('smart_money', 0)}/30",
            f"  排名加速:  {bd.get('rank_momentum', 0)}/20",
            f"  成交量质量: {bd.get('volume_quality', 0)}/15",
            f"  结构健康度: {bd.get('structure', 0)}/15",
            f"  多时间帧:  {bd.get('timeframe', 0)}/10",
            f"  风险折价:  {bd.get('risk_penalty', 0)}",
            "",
            f"  地址: <code>{addr}</code>",
            f"  价格: {price}",
            f"  成交额({sig.interval}): {vol}",
            f"  市值: {mc}",
        ]
        return "\n".join(lines)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_usd(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.2f}"
