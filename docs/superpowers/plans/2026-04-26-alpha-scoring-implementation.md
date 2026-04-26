# Alpha Scoring Engine — 实施计划

## 文件变更

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `src/scanner/models.py` | 修改 | 新增 `FilterResult`, `TokenRisk`, `ScoredToken`, `AlphaSignal` |
| `src/scanner/gmgn_client.py` | 修改 | 新增 `fetch_token_info`, `fetch_token_security` |
| `src/scanner/detector.py` | 重写 | 替换为两层评分引擎（硬过滤 + 机会评分） |
| `src/scanner/notifier.py` | 修改 | 更新消息格式（分数 + 因子明细） |
| `src/scanner/orchestrator.py` | 修改 | 插入冷却逻辑 + 新评分流程 |
| `src/shared/config.py` | 修改 | 新增评分/过滤/冷却配置 |
| `.env.example` | 修改 | 新增配置示例 |

## Task 1: 新增模型

`src/scanner/models.py` 新增：

```python
class FilterResult(BaseModel):
    passed: bool
    reason: str = ""

class TokenRisk(BaseModel):
    rug_risk: float = 0.0
    is_honeypot: bool = False
    bundler_ratio: float = 0.0
    rat_ratio: float = 0.0
    sniper_count: int = 0
    top10_holder_pct: float = 0.0

class ScoredToken(BaseModel):
    token: TrendingToken
    score: int
    breakdown: dict[str, int]  # factor_name -> score
    risk: TokenRisk | None = None
    passed_filters: bool = True
    filter_reason: str = ""

class AlphaSignal(BaseModel):
    token: ScoredToken
    level: str  # HIGH / MEDIUM / OBSERVE
    chain: str
    interval: str
    detected_at: datetime
    next_cooldown_until: datetime | None = None
```

## Task 2: 新增 GMGN API 方法

`src/scanner/gmgn_client.py` 新增：

```python
async def fetch_token_security(self, chain: str, address: str) -> TokenRisk | None:
    cmd = [self._cli_path, "token", "security", "--chain", chain, "--address", address, "--raw"]
    # 解析返回值中的 rug_risk, is_honeypot, bundler_trader_amount_rate, rat_trader_amount_rate, sniper_count, top10_holder_rate
```

## Task 3: 重写检测器

`src/scanner/detector.py` 重写：

```python
class AlphaScorer:
    def __init__(self, config: AlphaScorerConfig):
        # surge_threshold, spike_ratio, min_liquidity, max_rug_risk, etc.

    def hard_filter(self, token: TrendingToken, risk: TokenRisk | None) -> FilterResult:
        # 流动性 < $50K → reject
        # rug_risk > 0.8 → reject
        # bundler+rat > 70% → reject
        # smart_degen=0 & volume > $100K → reject
        # is_honeypot → reject

    def score(self, token: TrendingToken, prev: TrendingToken | None, risk: TokenRisk | None) -> ScoredToken:
        # 聪明钱领先 30分
        # 排名加速 20分
        # 成交量质量 15分
        # 结构健康度 15分
        # 多时间帧确认 10分
        # 风险折价 -10分
```

## Task 4: 更新通知格式

`src/scanner/notifier.py` — 更新 `_format_message` 输出带分数明细的 HTML 消息。

## Task 5: 集成冷却逻辑

`src/scanner/orchestrator.py` — `_run_chain` 中插入冷却判定：检查代币地址是否在冷却中。

## Task 6: 添加配置

`src/shared/config.py` 新增 8 个配置项（scanner_min_liquidity, scanner_max_rug_risk, scanner_max_bundler_rat_ratio, scanner_score_high_threshold, scanner_score_medium_threshold, scanner_score_low_threshold, scanner_cooldown_high_seconds, scanner_cooldown_medium_seconds）。
