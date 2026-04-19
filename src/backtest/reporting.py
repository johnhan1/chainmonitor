from __future__ import annotations

import json
from pathlib import Path

from src.shared.schemas.backtest import AttributionReport, BacktestConfig, BacktestRunReport


class BacktestReportExporter:
    def __init__(self, root_dir: str = "reports/backtest") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        report: BacktestRunReport,
        config: BacktestConfig,
        attribution: AttributionReport,
    ) -> dict[str, str]:
        base_name = f"{report.chain_id}_{report.run_id}"
        json_path = self.root_dir / f"{base_name}.json"
        csv_path = self.root_dir / f"{base_name}.csv"
        md_path = self.root_dir / f"{base_name}.md"

        json_payload = {
            "run": report.model_dump(mode="json"),
            "config": config.model_dump(mode="json"),
            "attribution": attribution.model_dump(mode="json"),
        }
        json_path.write_text(
            json.dumps(json_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_csv(csv_path, report, attribution)
        self._write_markdown(md_path, report, attribution)
        return {
            "json": str(json_path),
            "csv": str(csv_path),
            "md": str(md_path),
        }

    @staticmethod
    def _write_csv(path: Path, report: BacktestRunReport, attribution: AttributionReport) -> None:
        lines = [
            "section,key,trade_count,net_pnl_usd,win_rate",
            (
                "metrics,summary,"
                f"{report.metrics.trade_count},{report.metrics.net_pnl_usd},{report.metrics.win_rate}"
            ),
        ]
        for row in attribution.by_token:
            lines.append(f"by_token,{row.key},{row.trade_count},{row.net_pnl_usd},{row.win_rate}")
        for row in attribution.by_hour:
            lines.append(f"by_hour,{row.key},{row.trade_count},{row.net_pnl_usd},{row.win_rate}")
        for row in attribution.by_regime:
            lines.append(f"by_regime,{row.key},{row.trade_count},{row.net_pnl_usd},{row.win_rate}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _write_markdown(
        path: Path, report: BacktestRunReport, attribution: AttributionReport
    ) -> None:
        md_lines = [
            "# Backtest Report",
            "",
            f"- run_id: `{report.run_id}`",
            f"- chain_id: `{report.chain_id}`",
            f"- strategy_version: `{report.strategy_version}`",
            f"- status: `{report.status}`",
            "",
            "## 核心指标",
            "",
            f"- trade_count: `{report.metrics.trade_count}`",
            f"- net_pnl_usd: `{report.metrics.net_pnl_usd}`",
            f"- pf: `{report.metrics.pf}`",
            f"- expectancy: `{report.metrics.expectancy}`",
            f"- max_dd_pct: `{report.metrics.max_dd_pct}`",
            "",
            "## 归因（By Token）",
            "",
        ]
        for row in attribution.by_token[:10]:
            md_lines.append(f"- {row.key}: pnl={row.net_pnl_usd}, win_rate={row.win_rate}")
        path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
