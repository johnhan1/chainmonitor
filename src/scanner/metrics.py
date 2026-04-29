from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)


class ScannerMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.chain_duration = Histogram(
            "cm_scanner_chain_duration_seconds",
            "Duration per chain scan",
            ["chain", "interval"],
            buckets=(1, 5, 10, 15, 20, 30, 45, 60, 90, 120),
            registry=registry,
        )
        self.trending_duration = Histogram(
            "cm_scanner_trending_duration_seconds",
            "Duration of trending API call",
            ["chain", "interval"],
            buckets=(0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30),
            registry=registry,
        )
        self.trending_tokens = Counter(
            "cm_scanner_trending_tokens_total",
            "Number of tokens fetched from trending",
            ["chain"],
            registry=registry,
        )
        self.security_duration = Histogram(
            "cm_scanner_security_check_duration_seconds",
            "Duration of token security check",
            ["chain"],
            buckets=(0.1, 0.3, 0.5, 1, 2, 3, 5),
            registry=registry,
        )
        self.security_checks = Counter(
            "cm_scanner_security_checks_total",
            "Token security check results",
            ["chain", "status"],
            registry=registry,
        )


def start_metrics_server(port: int = 9101) -> None:
    start_http_server(port, registry=REGISTRY)
