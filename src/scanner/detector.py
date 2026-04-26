from __future__ import annotations

from src.scanner.models import AnomalyEvent, AnomalyType, Snapshot, TrendingToken


class Detector:
    def __init__(self, surge_threshold: int = 10, spike_ratio: float = 2.0) -> None:
        self._surge_threshold = surge_threshold
        self._spike_ratio = spike_ratio

    def detect(self, prev: Snapshot | None, curr: Snapshot) -> list[AnomalyEvent]:
        if prev is None:
            return []

        prev_map: dict[str, TrendingToken] = {t.address: t for t in prev.tokens}
        events: list[AnomalyEvent] = []

        for token in curr.tokens:
            prev_token = prev_map.get(token.address)

            if prev_token is None:
                events.append(
                    AnomalyEvent(
                        type=AnomalyType.NEW,
                        token=token,
                        chain=curr.chain,
                        reason=f"New token on {curr.interval} trending",
                    )
                )
                continue

            rank_change = prev_token.rank - token.rank
            if rank_change >= self._surge_threshold:
                events.append(
                    AnomalyEvent(
                        type=AnomalyType.SURGE,
                        token=token,
                        chain=curr.chain,
                        previous_rank=prev_token.rank,
                        rank_change=rank_change,
                        reason=(
                            f"Rank surged #{prev_token.rank} \u2192 #{token.rank} (+{rank_change})"
                        ),
                    )
                )

            reasons = []
            if (
                prev_token.volume_1m
                and token.volume_1m
                and prev_token.volume_1m > 0
                and token.volume_1m / prev_token.volume_1m >= self._spike_ratio
            ):
                ratio = token.volume_1m / prev_token.volume_1m
                reasons.append(f"volume {ratio:.1f}x")
            if (
                prev_token.smart_degen_count is not None
                and token.smart_degen_count is not None
                and prev_token.smart_degen_count > 0
                and token.smart_degen_count / prev_token.smart_degen_count >= self._spike_ratio
            ):
                ratio = token.smart_degen_count / prev_token.smart_degen_count
                reasons.append(f"smart_degen {ratio:.1f}x")

            if reasons:
                events.append(
                    AnomalyEvent(
                        type=AnomalyType.SPIKE,
                        token=token,
                        chain=curr.chain,
                        reason=", ".join(reasons),
                    )
                )

        return events
