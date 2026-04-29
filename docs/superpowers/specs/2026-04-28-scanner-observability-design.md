# Scanner 可观测性设计

> Date: 2026-04-28
> Status: Draft

## 问题

Scanner 当前是黑盒，只有最终信号可见（Telegram 推送），中间过程不可观测：

- 哪些 token 被过滤、为什么、各规则拦截量
- 评分分布（多少 token 在 0-10、10-20、边缘案例 45-54）
- 冷却命中率、信号产出率
- 各链对比

导致无法定位优化点：阈值是否合理？过滤规则偏严？评分线偏高？

## 设计原则

1. **数据分离** — Prometheus 只记系统健康（API 耗时、成功率），策略调优数据存入 DB + JSONL
2. **全覆盖** — 一条数据记录一个 token 的完整 pipeline 轨迹，不需 JOIN 就能分析任意维度
3. **持久化** — 终端关闭不丢数据，支持事后 SQL 分析

## 架构

### EventBus 模式

业务代码 `publish(event)`，不感知日志和指标。

```
orchestrator._run_chain()
  │
  ├─ TrendingFetched       ──→  Prometheus
  ├─ TokenSecurityChecked  ──→  Prometheus
  ├─ ChainScanCompleted    ──→  Prometheus
  │
  └─ for each token:
       └─ TokenProcessed   ──→  DB + JSONL + stdout
            ├─ 过滤结果 (passed/reason)
            ├─ 评分 (score + breakdown 6维)
            ├─ 信号 (level)
            └─ 冷却 (skipped)
```

### 模块依赖

```
__main__.py
  ├─ orchestrator.py → events.py
  ├─ events.py       → handlers.py
  ├─ cooldown.py     (已提取)
  ├─ handlers.py     → metrics.py, engine (DB), file (JSONL)
  └─ metrics.py      (精简)
```

| 文件 | 职责 |
|------|------|
| `events.py` | EventBus + 5 个事件 dataclass |
| `handlers.py` | StructuredLogHandler + MetricsHandler + DatabaseEventHandler + FileEventHandler |
| `metrics.py` | ScannerMetrics（5 个系统指标）+ start_metrics_server() |
| `cooldown.py` | 从 orchestrator 提取的冷却管理 |
| `orchestrator.py` | 使用 CooldownManager + EventBus，emit TokenProcessed 替代 4 个事件 |
| `__main__.py` | 组装 EventBus + 3 个 handler + 启动 metrics server |

## 事件定义

5 个事件，按两类数据分离：

### 系统监控（→ Prometheus）

```python
@dataclass
class TrendingFetched:
    chain: str
    interval: str
    token_count: int
    duration_ms: float
    success: bool

@dataclass
class TokenSecurityChecked:
    chain: str
    address: str
    symbol: str
    duration_ms: float
    success: bool

@dataclass
class ChainScanCompleted:
    chain: str
    interval: str
    total_duration_ms: float
    token_count: int
    signal_count: int
```

### 策略调优（→ DB + JSONL + stdout）

```python
@dataclass
class TokenProcessed:
    chain: str
    interval: str
    scanned_at: datetime
    address: str
    symbol: str
    filter_passed: bool
    filter_reason: str
    score_total: int | None
    score_breakdown: dict[str, int] | None
    signal_emitted: bool
    signal_level: str | None
    cooldown_skipped: bool
```

一条 `TokenProcessed` = 一个 token 的完整 pipeline 结果。`score_total` 和 `score_breakdown` 为 None 表示未通过硬过滤。

### EventBus

```python
class EventBus:
    def subscribe(self, event_type: type, handler: EventHandler) -> None: ...
    def publish(self, event: Any) -> None: ...
```

Handler 异常只打 log，不传播。

EVENT_TYPES 只导出 5 个事件，每个 handler 订阅自己关心的事件类型：

| Handler | 订阅的事件 |
|---------|-----------|
| MetricsHandler | TrendingFetched, TokenSecurityChecked, ChainScanCompleted |
| DatabaseEventHandler | TokenProcessed |
| FileEventHandler | TokenProcessed |
| StructuredLogHandler | TokenProcessed |

## Handler

### DatabaseEventHandler

接收 TokenProcessed，写入 `scanner_token_results` 表。

```python
class DatabaseEventHandler:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __call__(self, event: TokenProcessed) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO scanner_token_results
                        (chain, interval, scanned_at, address, symbol,
                         filter_passed, filter_reason,
                         score_total, score_breakdown,
                         signal_emitted, signal_level, cooldown_skipped)
                    VALUES
                        (:chain, :interval, :scanned_at, :address, :symbol,
                         :filter_passed, :filter_reason,
                         :score_total, CAST(:score_breakdown AS JSONB),
                         :signal_emitted, :signal_level, :cooldown_skipped)
                """),
                asdict(event)
            )
```

### FileEventHandler

接收 TokenProcessed，追加 JSON 行到按日轮转的文件。

```python
class FileEventHandler:
    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = log_dir
        self._file: TextIO | None = None
        self._date: str | None = None

    def __call__(self, event: TokenProcessed) -> None:
        self._ensure_file()
        self._file.write(json.dumps(asdict(event), default=str) + "\n")
        self._file.flush()

    def _ensure_file(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._date:
            if self._file:
                self._file.close()
            os.makedirs(self._log_dir, exist_ok=True)
            path = os.path.join(self._log_dir, f"scanner-analysis-{today}.jsonl")
            self._file = open(path, "a", encoding="utf-8")
            self._date = today
```

### StructuredLogHandler

只收 TokenProcessed，写入 `src.scanner.events` logger。每条日志 JSON 中包含所有事件字段，`message` 字段 = "TokenProcessed"。

```json
{
  "message": "TokenProcessed",
  "chain": "sol",
  "interval": "1m",
  "address": "0xabc...",
  "filter_passed": false,
  "filter_reason": "liquidity",
  "asctime": "2026-04-28 12:00:00",
  "levelname": "INFO",
  "name": "src.scanner.events"
}
```

### MetricsHandler

只处理系统事件，移除策略指标：

| 指标 | 类型 | Labels |
|------|------|--------|
| `cm_scanner_chain_duration_seconds` | Histogram | chain, interval |
| `cm_scanner_trending_duration_seconds` | Histogram | chain, interval |
| `cm_scanner_trending_tokens_total` | Counter | chain |
| `cm_scanner_security_check_duration_seconds` | Histogram | chain |
| `cm_scanner_security_checks_total` | Counter | chain, status |

**移除**：`cm_scanner_filter_rejections_total`、`cm_scanner_signals_total`、`cm_scanner_score`

## 持久化

### DB 表

Alembic migration 创建 `scanner_token_results`：

```sql
CREATE TABLE scanner_token_results (
    id BIGSERIAL PRIMARY KEY,
    chain VARCHAR(20) NOT NULL,
    interval VARCHAR(5) NOT NULL,
    scanned_at TIMESTAMPTZ NOT NULL,
    address VARCHAR(100) NOT NULL,
    symbol VARCHAR(50),
    filter_passed BOOLEAN NOT NULL,
    filter_reason VARCHAR(100),
    score_total INTEGER,
    score_breakdown JSONB,
    signal_emitted BOOLEAN NOT NULL DEFAULT FALSE,
    signal_level VARCHAR(10),
    cooldown_skipped BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scan_chain_time ON scanner_token_results (chain, scanned_at);
CREATE INDEX idx_scan_filter ON scanner_token_results (filter_passed, filter_reason);
CREATE INDEX idx_scan_score ON scanner_token_results (score_total);
CREATE INDEX idx_scan_signal ON scanner_token_results (signal_emitted, signal_level);
```

### JSONL 文件

`logs/scanner-analysis-YYYY-MM-DD.jsonl`，按天轮转，每行一个 TokenProcessed JSON。

### 可回答的分析问题

```sql
-- 过滤漏斗：各原因拦截量
SELECT filter_reason, COUNT(*) FROM scanner_token_results
WHERE NOT filter_passed GROUP BY filter_reason ORDER BY 2 DESC;

-- 通过率（按链）
SELECT chain,
  COUNT(*) FILTER(WHERE filter_passed) * 100.0 / COUNT(*) AS pass_rate
FROM scanner_token_results GROUP BY chain;

-- 评分分布
SELECT chain, score_total / 10 * 10 AS bucket, COUNT(*)
FROM scanner_token_results
WHERE filter_passed AND score_total IS NOT NULL
GROUP BY chain, bucket ORDER BY chain, bucket;

-- 边缘案例（45-54）：有多少、特征
SELECT score_total, signal_emitted, cooldown_skipped, COUNT(*)
FROM scanner_token_results
WHERE score_total BETWEEN 45 AND 54
GROUP BY score_total, signal_emitted, cooldown_skipped;

-- 信号率
SELECT chain,
  COUNT(*) FILTER(WHERE signal_emitted) * 100.0 / COUNT(*) AS signal_rate,
  COUNT(*) FILTER(WHERE filter_passed) AS after_filter,
  COUNT(*) AS total
FROM scanner_token_results GROUP BY chain;

-- 冷却影响
SELECT chain,
  COUNT(*) FILTER(WHERE cooldown_skipped) AS cooled,
  COUNT(*) FILTER(WHERE signal_emitted) AS sent
FROM scanner_token_results WHERE filter_passed GROUP BY chain;
```

## Config

`src/shared/config.py` 新增：

```python
scanner_metrics_port: int = 9101
```

## Orchestrator 变更

`_run_chain()` 中 token 循环 emit `TokenProcessed` 替代 4 个独立事件：

```python
for token in curr.tokens:
    risk = risks.get(token.address)
    fr = self._scorer.hard_filter(token, risk)
    score_total = None
    score_breakdown = None
    if fr.passed:
        scored = self._scorer.score(token, prev_map.get(token.address), risk)
        score_total = scored.score
        score_breakdown = scored.breakdown
    # check signals and cooldown
    ...
    self._event_bus.publish(TokenProcessed(
        chain=chain, interval=interval, scanned_at=t0,
        address=token.address, symbol=token.symbol,
        filter_passed=fr.passed, filter_reason=fr.reason,
        score_total=score_total, score_breakdown=score_breakdown,
        signal_emitted=..., signal_level=..., cooldown_skipped=...,
    ))
```

系统事件推送不变（TrendingFetched, TokenSecurityChecked, ChainScanCompleted）。

## 测试

- `test_events.py` — EventBus 订阅/发布、handler 异常隔离、5 个事件构造
- `test_handlers.py` — DatabaseEventHandler INSERT、FileEventHandler 写文件、MetricsHandler 指标更新、StructuredLogHandler 输出格式
- `test_cooldown.py` — 冷却判定、过期、pool_size
- `test_orchestrator.py` — TokenProcessed 事件发布验证、系统事件发布验证
- `test_migration.py` — scanner_token_results 表创建/回滚
