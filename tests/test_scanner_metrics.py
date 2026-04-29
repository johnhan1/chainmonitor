from __future__ import annotations

from prometheus_client import CollectorRegistry
from src.scanner.metrics import REGISTRY, ScannerMetrics, start_metrics_server


def test_metrics_created_in_registry() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    metrics.trending_tokens.labels(chain="sol").inc(5)
    val = registry.get_sample_value("cm_scanner_trending_tokens_total", {"chain": "sol"})
    assert val == 5.0


def test_chain_duration_histogram() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    metrics.chain_duration.labels(chain="sol", interval="1m").observe(10.5)
    count = registry.get_sample_value(
        "cm_scanner_chain_duration_seconds_count",
        {"chain": "sol", "interval": "1m"},
    )
    assert count == 1.0


def test_removed_metrics_not_in_registry() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    assert not hasattr(metrics, "filter_rejections")
    assert not hasattr(metrics, "signals")
    assert not hasattr(metrics, "score")


def test_start_metrics_server_runs() -> None:
    start_metrics_server(0)
    assert REGISTRY is not None
