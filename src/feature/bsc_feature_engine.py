from __future__ import annotations

from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput


class BscFeatureEngine:
    def build_features(self, ticks: list[MarketTickInput]) -> list[FeatureRowInput]:
        rows: list[FeatureRowInput] = []
        for tick in ticks:
            buy_sell_ratio = tick.buys_1m / max(tick.sells_1m, 1)
            churn = min(0.95, max(0.01, 1.0 / max(buy_sell_ratio, 1.0)))
            contract_risk = min(1.0, 0.1 + (tick.tx_count_1m % 15) / 100)
            lp_concentration = min(1.0, 0.2 + (tick.buys_1m % 50) / 100)
            holder_concentration = min(1.0, 0.35 + (tick.sells_1m % 45) / 100)
            wash_trade_score = min(1.0, (tick.tx_count_1m % 30) / 100)

            rows.append(
                FeatureRowInput(
                    chain_id=tick.chain_id,
                    token_id=tick.token_id,
                    ts_minute=tick.ts_minute,
                    netflow_usd_5m=(tick.buys_1m - tick.sells_1m) * tick.price_usd * 4,
                    netflow_usd_30m=(tick.buys_1m - tick.sells_1m) * tick.price_usd * 20,
                    large_buy_count_30m=max(0, tick.buys_1m // 6),
                    new_holder_30m=max(1, tick.tx_count_1m // 4),
                    holder_churn_24h=round(churn, 6),
                    contract_risk_score=round(contract_risk, 6),
                    lp_concentration=round(lp_concentration, 6),
                    holder_concentration_top10=round(holder_concentration, 6),
                    wash_trade_score=round(wash_trade_score, 6),
                    honeypot_flag=False,
                )
            )
        return rows
