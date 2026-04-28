# GMGN Scanner — 策略文档

> 当前代码状态，记录于 2026-04-28。后续修改请同步更新此文档。
> 最近更新：2026-04-28 — V2 改进（硬过滤调整为 penalty、加速度因子、冷却衰减、smart money 比例加权、多时间帧激活、安全查询并行化）

---

## 架构总览

```
[gmgn-cli] → GmgnClient → [trending 榜单数据]
                              ↓
                      AlphaScorer.hard_filter()
                              ↓ 通过
                      AlphaScorer.score()
                              ↓ ≥55分
                      ScannerOrchestrator (冷却判定)
                              ↓ 非冷却
                      TelegramNotifier.send_alpha()
```

## 数据流

### 扫描频率

| 数据源 | 频率 | 用途 |
|---|---|---|
| `1m` 热门榜 | 每 60 秒 | 捕获最早热度信号 |
| `1h` 热门榜 | 每 5 分钟 | 过滤持续性信号 |

每次扫描：4 条链 sequentially（sol → bsc → base → eth），每条链拉 top 50。

### 安全数据

流动性 < $100K 的代币使用 `asyncio.create_task` **并行**查询 `gmgn-cli token security`，获取六个风险指标：
- `rug_risk` — rug 风险评分 (0-1)
- `is_honeypot` — 貔貅检测
- `bundler_trader_amount_rate` — 捆绑盘占比
- `rat_trader_amount_rate` — 老鼠仓占比
- `sniper_count` — 狙击手数量
- `top10_holder_rate` — top10 持仓集中度

## 第一层：硬过滤（一票否决）

任一条件触发 → 跳过该代币，不入评分。

| 条件 | 阈值 | 默认值 | 逻辑 |
|---|---|---|---|
| 流动性下限 | `scanner_min_liquidity` | $50,000 | liquidity < threshold → reject |
| Rug 风险 | `scanner_max_rug_risk` | 0.8 | rug_risk > 0.8 → reject |
| 捆绑+老鼠仓 | `scanner_max_bundler_rat_ratio` | 0.7 | bundler_ratio + rat_ratio > 0.7 → reject |
| 貔貅 | 硬编码 | — | is_honeypot = true → reject |
> 注意：若无 risk 数据（API 调用失败），bundler/rat/honeypot/rug 检查跳过，只检查流动性。

## 第二层：机会评分（max 100）

### 因子明细

#### ① 聪明钱领先（max 30）

依赖 `smart_degen_count`：

**有历史数据：**

| 条件 | 得分 |
|---|---|
| delta ≥ 5 | 30 |
| delta ≥ 3 | 25 |
| delta ≥ 1 | 20 |
| 无 delta，但 count ≥ 10 | 15 |

**无历史数据（新上榜）：**

| 条件 | 得分 |
|---|---|
| smart_degen_count ≥ 5 | 15 |
| smart_degen_count ≥ 3 | 10 (兜底) |
| 其他 | 0 |

> **主要 alpha 来源。** delta 越大，说明聪明钱正在集中进场。但只看 count 不看金额和买入顺序，是已知缺陷。

#### ② 排名加速度（max 25）

依赖排名变化（`prev.rank - curr.rank`，正数=上升）：

| 排名上升 | 得分 |
|---|---|
| ≥ 40 位 | 25 |
| ≥ 20 位 | 20 |
| ≥ 10 位 | 15 |
| ≥ 5 位 | 10 |
| > 0 位 | 5 |
| 无历史数据（新上榜） | 10 |

> **速度比绝对位置重要。** #50→#25 的早期信号价值 > #3→#1。
> 缺点：容易被微盘币低基数冲榜欺骗，需要结合流动性和成交额绝对值。

#### ③ 成交量质量（max 15）

依赖 `volume_1m / liquidity` 比值：

| vol/liquid 比值 | 得分 |
|---|---|
| 0.5x ~ 5.0x (理想) | 15 |
| 0.1x ~ 10.0x (可接受) | 10 |
| 其他 | 5 |
| 无流动性但 volume > 0 | 5 (兜底) |

> 太高可能是机器人对倒（无真实需求），太低可能是没人气。
> 新币早期 volume/liquidity 可能很高，这是正常现象。

#### ④ 结构健康度（max 15）

基线 10 分，加分项：

| 条件 | 加分 |
|---|---|
| bundler_ratio < 0.2 | +3 |
| rat_ratio < 0.2 | +2 |
| top10_holder_pct < 50% | +3 |
| sniper_count < 5 | +2 |

> 无 risk 数据时返回基线 10 分。

#### ⑤ 成交量加速度（max 15）

依赖 `curr.volume_1m / prev.volume_1m` 比值（仅 prev 存在时）：

| 条件 | 得分 |
|---|---|
| > 3x | 15 |
| > 2x | 10 |
| > 1.5x | 5 |
| 无历史数据 | 0 |

> meme 币最有效的 alpha 之一 — 成交量突然放大通常是爆发前兆。

#### ⑥ 多时间帧确认（max 10）

orchestrator 在扫描 1m 榜时，检查 token 是否同时出现在最近的 1h 榜中。若是则加 10 分。

> 设计上不适合做硬门槛，只做加分项。否则会降低早期捕捉能力。

#### ⑦ 风险折价（max -10）

| 条件 | 扣分 |
|---|---|
| rug_risk > 0.7 | -10 |
| rug_risk > 0.5 | -5 |
| is_honeypot | -10 |
| **smart_degen=0 且 volume_1m > $100K** | **-10 (新增)** |

> 最后一项不依赖 risk 数据。原为硬过滤条件，V2 改为 penalty 避免误杀早期 alpha。

### 总分计算

```
Score = smart_money + rank_momentum + volume_quality + structure + volume_acceleration + timeframe + risk_penalty
Score = max(0, min(100, Score))
```

> 理论 max > 100（当前 ~115），但 cap 在 100。设计上允许总分超限，高分段竞争更激烈。

## 第三层：推送阈值 + 冷却

### 等级划分

| 分数区间 | 等级 | 推送行为 |
|---|---|---|
| ≥ 75 | 🔴 HIGH | 立即推送 |
| 65 - 74 | 🟡 MEDIUM | 推送 |
| 55 - 64 | 🔵 OBSERVE | 推送 |
| < 55 | — | 不推送 |

阈值通过 `CM_SCANNER_SCORE_HIGH_THRESHOLD` / `CM_SCANNER_SCORE_MEDIUM_THRESHOLD` / `CM_SCANNER_SCORE_LOW_THRESHOLD` 配置。

### 冷却机制

内存字典 `dict[address → expire_timestamp]` + 命中计数器，进程重启后清空。

**衰减机制**：同一代币重复命中时，衰减分数而非屏蔽：

| 命中次数 | 衰减系数 |
|---|---|
| 1 | 1.0 (完整分数) |
| 2 | 0.6 |
| 3+ | 0.3 |

**冷却时长**：

| 信号等级 | 冷却时间 | 可配置 |
|---|---|---|
| HIGH | 15 分钟 | `scanner_cooldown_high_seconds` |
| MEDIUM | 30 分钟 | `scanner_cooldown_medium_seconds` |
| OBSERVE | 5 分钟 | `scanner_cooldown_observe_seconds` (新增) |

衰减后分数低于阈值时消息中的分数会降低，但推送仍按原始检测等级发送。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CM_SCANNER_MIN_LIQUIDITY` | 50000 | 硬过滤：流动性下限 ($) |
| `CM_SCANNER_MAX_RUG_RISK` | 0.8 | 硬过滤：rug 风险上限 |
| `CM_SCANNER_MAX_BUNDLER_RAT_RATIO` | 0.7 | 硬过滤：捆绑+老鼠仓占比上限 |
| `CM_SCANNER_SCORE_HIGH_THRESHOLD` | 75 | HIGH 阈值 |
| `CM_SCANNER_SCORE_MEDIUM_THRESHOLD` | 65 | MEDIUM 阈值 |
| `CM_SCANNER_SCORE_LOW_THRESHOLD` | 55 | OBSERVE 阈值 |
| `CM_SCANNER_COOLDOWN_HIGH_SECONDS` | 900 | HIGH 冷却 (秒) |
| `CM_SCANNER_COOLDOWN_MEDIUM_SECONDS` | 1800 | MEDIUM 冷却 (秒) |
| `CM_SCANNER_COOLDOWN_OBSERVE_SECONDS` | 300 | OBSERVE 冷却 (秒) |
| `CM_SCANNER_METRICS_PORT` | 9101 | Scanner Prometheus metrics HTTP server port |
| `CM_SCANNER_ENABLED` | false | Scanner 总开关 |
| `CM_SCANNER_CHAINS` | "sol,bsc,base,eth" | 监控链列表 |
| `CM_SCANNER_SURGE_THRESHOLD` | 10 | 排名跃升阈值（硬过滤用） |
| `CM_SCANNER_SPIKE_RATIO` | 2.0 | 量价倍增阈值 |
| `CM_SCANNER_INTERVAL_1M_SECONDS` | 60 | 1m 榜轮询间隔 |
| `CM_SCANNER_INTERVAL_1H_SECONDS` | 300 | 1h 榜轮询间隔 |
| `CM_SCANNER_TRENDING_LIMIT` | 50 | 每榜拉取代币数 |

## TG 消息格式

```
🔴 [85] SOL 1m — $PEPE

📊 评分明细
  聪明钱领先:  28/30
  排名加速:   18/25
  成交量质量:  12/15
  成交量加速:  15/15
  结构健康度:  13/15
  多时间帧:   10/10
  风险折价:   -4

  地址: 0xabc…def
  价格: $0.0123
  成交额(1m): $45.2K
  市值: $1.2M
```

## 可观测性

### 结构化日志

Scanner 在 pipeline 各环节输出 JSON 结构化事件日志，每条日志的 `message` 字段标识事件类型：

| 事件 | 触发点 | 说明 |
|------|--------|------|
| `ChainScanStarted` | 链扫描开始 | chain, interval, timestamp |
| `TrendingFetched` | trending API 返回 | token_count, duration_ms, success |
| `TokenSecurityChecked` | 安全查询完成 | address, duration_ms, success |
| `TokenFiltered` | 硬过滤判定 | address, passed, reason |
| `TokenScored` | 评分完成 | address, total_score, breakdown |
| `SignalEmitted` | 信号推送 | address, level, score |
| `CooldownSkipped` | 冷却跳过 | address, symbol |
| `ChainScanCompleted` | 链扫描结束 | total_duration_ms, token_count, signal_count |

### Prometheus 指标

Scanner 在 `CM_SCANNER_METRICS_PORT`（默认 9101）暴露 `/metrics` 端点：

| 指标 | 类型 | 说明 |
|------|------|------|
| `cm_scanner_chain_duration_seconds` | Histogram | 每链扫描耗时 |
| `cm_scanner_trending_duration_seconds` | Histogram | trending API 调用耗时 |
| `cm_scanner_trending_tokens_total` | Counter | 获取的代币总数 |
| `cm_scanner_security_check_duration_seconds` | Histogram | 安全查询耗时 |
| `cm_scanner_security_checks_total` | Counter | 安全查询结果 (ok/fail) |
| `cm_scanner_filter_rejections_total` | Counter | 硬过滤拦截原因分布 |
| `cm_scanner_signals_total` | Counter | 信号等级分布 |
| `cm_scanner_score` | Histogram | 评分分布 |

### 评分分布监控（日志）

`AlphaScorer` 内部维护一个 11 bucket histogram（0,10,20,...,100），每扫描 100 个 token 输出一行 CSV 格式日志：

```
Score histogram (n=100): [12,8,15,20,18,10,7,5,3,1,1]
```

用于监控评分分布是否健康（目标：均分 ~50，std ~15），辅助权重校准。

## 已知问题

1. **第一轮无信号** — prev snapshot 为空时 `detect()` 返回 []，需等一轮积累历史数据
2. **聪明钱只看 count** — 不看净买入金额和入场时机，信息量不足。API 数据限制，暂时只能做 count 层面的增强（比例加权）
3. **冷却非持久化** — 内存 dict 重启丢失
4. **命中计数不衰减** — `_hit_counts` 永久保留，不会因长时间无活动而重置
