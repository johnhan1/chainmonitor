# GMGN 热门榜异动扫描工具 — 设计文档

## 概述

基于 GMGN CLI (`gmgn-cli`) 构建热门代币异动扫描工具，检测代币新上榜、排名飙升、量价/聪明钱暴增等异动信号，通过 Telegram 推送通知。

## 架构

```
                     ┌─────────────────────┐
                     │   ScannerOrchestrator│
                     │   (async main loop)  │
                     └──┬──────┬──────┬────┘
                        │      │      │
              ┌─────────┘      │      └──────────┐
              ▼                ▼                  ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
     │ GmgClient    │ │  Detector    │ │ TelegramNotifier │
     │ (subprocess) │ │ (diff引擎)   │       │ (httpx)          │
     └──────┬───────┘ └──────┬───────┘ └──────────────────┘
            │                │
            ▼                ▼
     ┌──────────────┐ ┌──────────────┐
     │  gmgn-cli    │ │ SnapshotStore│
     │  market      │ │  (DB table)  │
     │  trending    │ └──────────────┘
     └──────────────┘
```

## 模块

### 1. `src/scanner/models.py`

```python
class TrendingToken(BaseModel):
    address: str
    symbol: str
    name: str
    price_usd: float
    volume_1m: float | None
    volume_1h: float | None
    market_cap: float | None
    liquidity: float | None
    smart_degen_count: int | None
    rank: int
    chain: str

class Snapshot(BaseModel):
    chain: str
    interval: str          # "1m" | "1h"
    tokens: list[TrendingToken]
    taken_at: datetime

class AnomalyType(str, Enum):
    NEW = "new"
    SURGE = "surge"
    SPIKE = "spike"

class AnomalyEvent(BaseModel):
    type: AnomalyType
    token: TrendingToken
    chain: str
    previous_rank: int | None
    rank_change: int | None
    reason: str
```

### 2. `src/scanner/gmgn_client.py`

- 通过 `asyncio.create_subprocess_exec` 调用 `gmgn-cli`
- 命令: `gmgn-cli market trending --chain {chain} --interval {interval} --limit 50 --raw`
- 解析 stdout JSON → `list[TrendingToken]`
- 超时 30s，失败有日志和指标

### 3. `src/scanner/snapshot_store.py`

快照存 PostgreSQL，表 `scanner_snapshots`：

```sql
CREATE TABLE scanner_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    chain       VARCHAR(10) NOT NULL,
    interval    VARCHAR(5) NOT NULL,
    snapshot_data JSONB NOT NULL,
    taken_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(chain, interval)
);
```

方法：
- `load(chain, interval) → Snapshot | None`
- `save(chain, interval, snapshot: Snapshot)`
- `clear(chain, interval)`

### 4. `src/scanner/detector.py`

核心逻辑：对比新快照和旧快照，返回异动列表。

| 异动 | 条件 | 优先级 |
|---|---|---|
| NEW | 地址不在旧快照中 | HIGH |
| SURGE | 排名上升 ≥ SURGE_THRESHOLD (默认10) | MEDIUM |
| SPIKE | 成交量/聪明钱数倍增 ≥ SPIKE_RATIO (默认2.0) | MEDIUM |

检测后更新快照。

### 5. `src/scanner/notifier.py`

- 使用 `httpx` (项目已有依赖) 调用 Telegram Bot API
- 消息格式：MarkdownV2，按优先级分组发送
- 支持消息聚合（多条异动合并一条发送，避免刷屏）
- 方法: `send_anomalies(chain, interval, events: list[AnomalyEvent])`

### 6. `src/scanner/orchestrator.py`

主循环：

```python
class ScannerOrchestrator:
    def __init__(self, chains: list[str]):
        self.client = GmgnClient()
        self.detector = Detector(...)
        self.notifier = TelegramNotifier(...)
        self.store = SnapshotStore(...)
        self.chains = chains

    async def run_cycle(self):
        for chain in self.chains:
            curr = await self.client.fetch_trending(chain, "1m")
            prev = await self.store.load(chain, "1m")
            events = self.detector.detect(prev, curr)
            if events:
                await self.notifier.send_anomalies(chain, "1m", events)
            await self.store.save(chain, "1m", curr)

        # 每5分钟执行一次 1h 榜扫描
        if self._should_run_1h():
            for chain in self.chains:
                curr = await self.client.fetch_trending(chain, "1h")
                prev = await self.store.load(chain, "1h")
                events = self.detector.detect(prev, curr)
                if events:
                    await self.notifier.send_anomalies(chain, "1h", events)
                await self.store.save(chain, "1h", curr)
```

启动方式：独立 `asyncio.run()` 循环，通过 `dev.ps1` 管理生命周期。

## 前提条件

- `gmgn-cli` 需全局安装：`npm install -g gmgn-cli`
- 需申请 GMGN API Key 并配置（参考 `gmgn.md` 第 3 节）
- 需 Telegram Bot Token（通过 @BotFather 创建）和 Chat ID

## 数据库迁移

新增 `scanner_snapshots` 表需创建 Alembic 迁移:

```bash
.\scripts\db-revision.ps1 -Message "add_scanner_snapshots"
```

## 配置 (`settings.py`)

```python
# GMGN
cm_gmgn_api_key: str = ""
cm_gmgn_cli_path: str = "gmgn-cli"

# Telegram
cm_telegram_bot_token: str = ""
cm_telegram_chat_id: str = ""

# Scanner
cm_scanner_enabled: bool = False
cm_scanner_chains: list[str] = field(default_factory=lambda: ["sol", "bsc", "base", "eth"])
cm_scanner_surge_threshold: int = 10
cm_scanner_spike_ratio: float = 2.0
cm_scanner_interval_1m_seconds: int = 60
cm_scanner_interval_1h_seconds: int = 300
cm_scanner_trending_limit: int = 50
```

## TG 消息模板

每条异动消息格式（MarkdownV2）：

```
🔥 *SOL 1m 异动*

🆕 *NEW* \-\- `$SYMBOL`
  地址: `0x1234…5678`
  价格: $0\.0123
  成交额\(1m\): $45\.2K
  聪明钱: 12
  市值: $1\.2M

⬆️ *SURGE* \-\- `$SYMBOL` \(#3 → #1, +12\)
  成交额\(1m\): $234K

🔥 *SPIKE* \-\- `$SYMBOL` \(成交量 \+350%\)
  成交额\(1m\): $89K ← $19\.5K
```

## 数据流

1. `run_cycle()` 按 chain 遍历
2. 每个 chain：调 `gmgn-cli` → 解析 → 加载上一轮快照 → 对比检测 → 有异动则发 TG → 保存新快照
3. 休眠至下一周期

## 错误处理

- `gmgn-cli` 调用失败（超时/非零退出）：记录日志 + Prometheus counter，跳过该 chain，不影响下一 chain
- TG 发送失败：记录日志，不重试（避免阻塞下一轮）
- DB 写入失败：记录日志，继续运行（异动检测依赖内存状态，下一轮会自动覆盖）

## 度量

- `cm_scanner_cycles_total{chain, status="ok|error"}`
- `cm_scanner_anomalies_total{chain, type="new|surge|spike"}`
- `cm_scanner_gmgn_duration_seconds{chain}`

## 部署变更

- `.env.example` 需追加 `CM_GMGN_API_KEY`、`CM_TELEGRAM_BOT_TOKEN`、`CM_TELEGRAM_CHAT_ID`、`CM_SCANNER_ENABLED`
- `dev.ps1` 新增 `scanner` 命令，管理 scanner 生命周期

## 测试策略

- `GmgnClient`：mock subprocess，验证命令构造和 JSON 解析
- `Detector`：构造快照 fixture，验证 NEW/SURGE/SPIKE 检测逻辑
- `Notifier`：mock httpx，验证消息格式和发送
- `Orchestrator`：mock 三个依赖，验证编排流程
