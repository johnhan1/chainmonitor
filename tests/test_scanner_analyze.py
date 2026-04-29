from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec

from sqlalchemy.engine import Engine
from src.scanner.analyze import ReportGenerator, ScannerAnalyzer, _parse_args


class _MockRow:
    """A row-like object supporting attribute and _mapping access."""

    def __init__(self, **kwargs: Any) -> None:
        self._mapping = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, str):
            return self._mapping[key]
        return list(self._mapping.values())[key]


def _make_mock_engine(*result_sets: list[dict[str, Any]]) -> Engine:
    """Build a fake Engine returning different rows per execute call."""
    engine = create_autospec(Engine, instance=True)
    conn = engine.connect.return_value.__enter__.return_value
    queue = list(result_sets)

    def execute_side_effect(*args: Any, **kwargs: Any) -> list[_MockRow]:
        if queue:
            return [_MockRow(**d) for d in queue.pop(0)]
        return []

    conn.execute.side_effect = execute_side_effect
    return engine


# ── ScannerAnalyzer ─────────────────────────────────────────────────


def test_scanner_analyzer_analyze_returns_all_10_keys() -> None:
    engine = _make_mock_engine(
        [
            {
                "total_records": 1,
                "chain_count": 1,
                "unique_tokens": 1,
                "days_with_data": 1,
                "passed_count": 1,
                "filtered_count": 0,
                "signal_count": 0,
                "cooldown_count": 0,
                "avg_score_passed": 50.0,
                "avg_score_all": 50.0,
            }
        ],
        [{"reason": "test", "count": 1}],
        [{"chain": "bsc", "total": 1, "passed": 1, "pass_rate": 100.0}],
        [{"day": "2024-01-01", "total": 1, "reject_rate": 0.0}],
        [{"bucket": 1, "range_start": 0, "count": 1}],
        [{"chain": "bsc", "count": 1, "avg_score": 50.0, "median": 50.0, "stddev": 0.0}],
        [{"level": "HIGH", "count": 0, "avg_score": 0.0}],
        [{"chain": "bsc", "total": 1, "signals": 0, "signal_rate": 0.0}],
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
                "sample_count": 0,
            }
        ],
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
            }
        ],
        [
            {
                "level": "HIGH",
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
                "sample_count": 0,
            }
        ],
        [
            {
                "chain": "bsc",
                "total_scans": 1,
                "unique_tokens": 1,
                "passed": 1,
                "pass_rate": 100.0,
                "avg_score": 50.0,
                "signals": 0,
                "signal_rate_of_passed": 0.0,
                "cooldowns": 0,
            }
        ],
        [{"hour": 0, "count": 0, "signals": 0, "avg_score": 0.0}],
        [{"dow": 0, "count": 0, "signals": 0, "avg_score": 0.0}],
        [{"day": "2024-01-01", "count": 0, "signals": 0, "avg_score": 0.0}],
        [{"symbol": "TEST", "address": "0x1", "chain": "bsc", "count": 1}],
        [{"symbol": "TEST", "address": "0x1", "chain": "bsc", "total": 1, "signal_count": 0}],
        [{"symbol": "TEST", "address": "0x1", "chain": "bsc", "count": 1, "avg_score": 50.0}],
        [{"total_skipped": 0, "total": 1, "avg_score_skipped": 0.0}],
        [{"chain": "bsc", "skipped": 0, "total": 1, "avg_score_skipped": 0.0}],
        [{"band": "0-54", "count": 1, "signals": 0}],
        [
            {
                "high_current": 0,
                "high_minus": 0,
                "high_plus": 0,
                "medium_current": 0,
                "medium_minus": 0,
                "medium_plus": 0,
                "observe_current": 0,
                "observe_minus": 0,
                "observe_plus": 0,
            }
        ],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    data = analyzer.analyze()
    expected_keys = {
        "overview",
        "filter_analysis",
        "score_distribution",
        "signal_analysis",
        "factor_breakdown",
        "chain_comparison",
        "temporal_patterns",
        "token_spotlight",
        "cooldown_analysis",
        "threshold_sensitivity",
    }
    assert set(data.keys()) == expected_keys


def test_overview_returns_expected_fields() -> None:
    engine = _make_mock_engine(
        [
            {
                "total_records": 100,
                "chain_count": 3,
                "unique_tokens": 50,
                "days_with_data": 7,
                "passed_count": 60,
                "filtered_count": 40,
                "signal_count": 20,
                "cooldown_count": 5,
                "avg_score_passed": 65.5,
                "avg_score_all": 55.0,
            },
        ]
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._overview()
    assert result["total_records"] == 100
    assert result["chain_count"] == 3
    assert result["pass_rate"] == 60.0
    assert result["signal_rate"] == 20.0
    assert result["avg_score_passed"] == 65.5


def test_filter_analysis_returns_three_keys() -> None:
    engine = _make_mock_engine(
        [],
        [],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._filter_analysis()
    assert set(result.keys()) == {"rejection_reasons", "by_chain", "daily_trend"}
    assert result["rejection_reasons"] == []
    assert result["by_chain"] == []
    assert result["daily_trend"] == []


def test_score_distribution_returns_histogram_and_per_chain() -> None:
    engine = _make_mock_engine(
        [],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._score_distribution()
    assert result["histogram"] == []
    assert result["per_chain"] == []


def test_signal_analysis_returns_by_level_and_by_chain() -> None:
    engine = _make_mock_engine(
        [],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._signal_analysis()
    assert result["by_level"] == []
    assert result["by_chain"] == []


def test_factor_breakdown_returns_keys() -> None:
    engine = _make_mock_engine(
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
                "sample_count": 0,
            }
        ],
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
            }
        ],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._factor_breakdown()
    assert "overall_averages" in result
    assert "overall_ratios" in result
    assert result["sample_count"] == 0
    assert result["by_signal_level"] == []


def test_chain_comparison_returns_list() -> None:
    engine = _make_mock_engine([])
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._chain_comparison()
    assert isinstance(result, list)
    assert result == []


def test_temporal_patterns_returns_hour_dow_daily() -> None:
    engine = _make_mock_engine(
        [],
        [],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._temporal_patterns()
    assert result["by_hour"] == []
    assert result["by_dow"] == []
    assert result["daily_trend"] == []


def test_token_spotlight_returns_three_lists() -> None:
    engine = _make_mock_engine(
        [],
        [],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._token_spotlight()
    assert result["most_scanned"] == []
    assert result["most_signals"] == []
    assert result["top_avg_score"] == []


def test_cooldown_analysis_returns_expected_keys() -> None:
    engine = _make_mock_engine(
        [{"total_skipped": 0, "total": 1, "avg_score_skipped": 0.0}],
        [],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._cooldown_analysis()
    assert result["total_skipped"] == 0
    assert result["skip_rate"] == 0.0
    assert result["avg_score_skipped"] == 0.0
    assert result["by_chain"] == []


def test_threshold_sensitivity_returns_bands_and_sensitivity() -> None:
    engine = _make_mock_engine(
        [],
        [
            {
                "high_current": 0,
                "high_minus": 0,
                "high_plus": 0,
                "medium_current": 0,
                "medium_minus": 0,
                "medium_plus": 0,
                "observe_current": 0,
                "observe_minus": 0,
                "observe_plus": 0,
            }
        ],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    result = analyzer._threshold_sensitivity()
    assert result["current_bands"] == []
    assert "high" in result["sensitivity"]
    assert "medium" in result["sensitivity"]
    assert "observe" in result["sensitivity"]


def test_analyze_uses_sanitized_engine() -> None:
    engine = _make_mock_engine(
        [
            {
                "total_records": 10,
                "chain_count": 1,
                "unique_tokens": 5,
                "days_with_data": 1,
                "passed_count": 8,
                "filtered_count": 2,
                "signal_count": 3,
                "cooldown_count": 1,
                "avg_score_passed": 70.0,
                "avg_score_all": 60.0,
            }
        ],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
                "sample_count": 0,
            }
        ],
        [
            {
                "smart_money": 0.0,
                "rank_momentum": 0.0,
                "volume_quality": 0.0,
                "structure": 0.0,
                "volume_acceleration": 0.0,
                "timeframe": 0.0,
                "risk_penalty": 0.0,
            }
        ],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [{"total_skipped": 0, "total": 10, "avg_score_skipped": 0.0}],
        [],
        [],
        [
            {
                "high_current": 0,
                "high_minus": 0,
                "high_plus": 0,
                "medium_current": 0,
                "medium_minus": 0,
                "medium_plus": 0,
                "observe_current": 0,
                "observe_minus": 0,
                "observe_plus": 0,
            }
        ],
    )
    analyzer = ScannerAnalyzer(engine, days=7)
    data = analyzer.analyze()
    assert data["overview"]["total_records"] == 10
    conn = engine.connect.return_value.__enter__.return_value
    assert conn.execute.called


def test_since_calculation() -> None:
    engine = _make_mock_engine()
    analyzer = ScannerAnalyzer(engine, days=14)
    expected = datetime.now(UTC) - timedelta(days=14)
    diff = abs((analyzer._since - expected).total_seconds())
    assert diff < 5


# ── ReportGenerator ─────────────────────────────────────────────────


def test_report_generator_to_markdown_has_sections() -> None:
    data: dict[str, Any] = {
        "overview": {
            "total_records": 100,
            "chain_count": 3,
            "unique_tokens": 50,
            "days_with_data": 7,
            "pass_rate": 60.0,
            "filter_rate": 40.0,
            "signal_rate": 20.0,
            "cooldown_rate": 5.0,
            "avg_score_passed": 65.5,
            "avg_score_all": 55.0,
        },
        "filter_analysis": {"rejection_reasons": [], "by_chain": [], "daily_trend": []},
        "score_distribution": {"histogram": [], "per_chain": []},
        "signal_analysis": {"by_level": [], "by_chain": []},
        "factor_breakdown": {
            "overall_averages": {},
            "overall_ratios": {},
            "sample_count": 0,
            "by_signal_level": [],
        },
        "chain_comparison": [],
        "temporal_patterns": {"by_hour": [], "by_dow": [], "daily_trend": []},
        "token_spotlight": {"most_scanned": [], "most_signals": [], "top_avg_score": []},
        "cooldown_analysis": {
            "total_skipped": 0,
            "skip_rate": 0.0,
            "avg_score_skipped": 0.0,
            "by_chain": [],
        },
        "threshold_sensitivity": {"current_bands": [], "sensitivity": {}},
    }
    gen = ReportGenerator(data)
    md = gen.to_markdown()
    assert "Scanner 分析报告" in md
    assert "全局概览" in md
    assert "过滤管道分析" in md
    assert "分数分布" in md
    assert "信号分析" in md
    assert "因子拆解" in md
    assert "链对比" in md
    assert "时间模式" in md
    assert "代币聚焦" in md
    assert "冷却分析" in md
    assert "阈值敏感性" in md


def test_report_generator_to_json_has_metadata() -> None:
    data: dict[str, Any] = {"overview": {"total_records": 10, "days_with_data": 7}}
    gen = ReportGenerator(data)
    j = gen.to_json()
    parsed = json.loads(j)
    assert "metadata" in parsed
    assert parsed["metadata"]["total_records"] == 10
    assert parsed["overview"] == data["overview"]


def test_report_generator_empty_data() -> None:
    gen = ReportGenerator({})
    md = gen.to_markdown()
    assert isinstance(md, str)
    j = gen.to_json()
    parsed = json.loads(j)
    assert "metadata" in parsed


def test_report_generator_handles_histogram_bars() -> None:
    data: dict[str, Any] = {
        "overview": {
            "total_records": 0,
            "chain_count": 0,
            "unique_tokens": 0,
            "days_with_data": 0,
            "pass_rate": 0.0,
            "filter_rate": 0.0,
            "signal_rate": 0.0,
            "cooldown_rate": 0.0,
            "avg_score_passed": 0.0,
            "avg_score_all": 0.0,
        },
        "filter_analysis": {"rejection_reasons": [], "by_chain": [], "daily_trend": []},
        "score_distribution": {
            "histogram": [
                {"range_start": 0, "range_end": 10, "count": 5},
                {"range_start": 10, "range_end": 20, "count": 15},
                {"range_start": 20, "range_end": 30, "count": 10},
            ],
            "per_chain": [],
        },
        "signal_analysis": {"by_level": [], "by_chain": []},
        "factor_breakdown": {
            "overall_averages": {},
            "overall_ratios": {},
            "sample_count": 0,
            "by_signal_level": [],
        },
        "chain_comparison": [],
        "temporal_patterns": {"by_hour": [], "by_dow": [], "daily_trend": []},
        "token_spotlight": {"most_scanned": [], "most_signals": [], "top_avg_score": []},
        "cooldown_analysis": {
            "total_skipped": 0,
            "skip_rate": 0.0,
            "avg_score_skipped": 0.0,
            "by_chain": [],
        },
        "threshold_sensitivity": {"current_bands": [], "sensitivity": {}},
    }
    gen = ReportGenerator(data)
    md = gen.to_markdown()
    assert "█" in md
    assert "0-10" in md


# ── CLI ─────────────────────────────────────────────────────────────


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.days == 7
    assert args.output == ""
    assert args.json is False


def test_parse_args_custom() -> None:
    args = _parse_args(["--days", "14", "--output", "report.md", "--json"])
    assert args.days == 14
    assert args.output == "report.md"
    assert args.json is True


def test_parse_args_json_flag() -> None:
    args = _parse_args(["--json"])
    assert args.json is True
