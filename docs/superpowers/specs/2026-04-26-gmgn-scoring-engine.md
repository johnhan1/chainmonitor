# GMGN Scanner Alpha Scoring Engine — 设计文档

## 概述

将当前的简单 NEW/SURGE/SPIKE 检测替换为两层评分模型：先硬过滤，再综合评分，最终生成 alpha 信号推送到 TG。

## 两层模型

```
第一层：硬过滤（一票否决）
  ↓ 通过
第二层：机会评分（0-100）
  ↓ 达到阈值
第三层：冷却判定
  ↓ 可推送
发送 TG 通知
```

## 第一层：硬过滤

任一条件触发 → 直接跳过，不入评分：

| 条件 | 参数 | 可配置 |
|---|---|---|
| 流动性 < 下限 | liquidity < $50K | `scanner_min_liquidity` |
| Rug 风险过高 | rug_risk > 0.8 | `scanner_max_rug_risk` |
| 捆绑/老鼠仓占比过高 | bundler+rat > 70% | `scanner_max_bundler_rat_ratio` |
| 聪明钱为 0 但成交异常 | smart_degen=0 & volume_1m > $100K | 硬编码 |
| 貔貅检测 | is_honeypot = true | 硬编码 |

注：rug_risk、bundler/rat 数据来自 `gmgn-cli token security`，非 trending 接口。硬过滤命中日志记录，方便调参。

## 第二层：机会评分

| 因子 | 权重 | 数据来源 | 计算方式 |
|---|---|---|---|
| 聪明钱领先 | 30 | trending + token info | smart_degen 增量 + 净买入金额变化 |
| 排名加速度 | 20 | trending 历史 | 单位时间排名爬升速度 |
| 成交量质量 | 15 | trending | volume/liquidity 比值 + volume 绝对值 |
| 结构健康度 | 15 | token security + holders | top10 集中度、bundler/rat/sniper 占比的逆向评分 |
| 多时间帧确认 | 10 | trending (1m vs 1h) | 同时在 1m 和 1h 榜 +10，仅 1m 榜 +5，仅 1h 榜 +2 |
| 风险折价 | -10 | token security | rug_risk > 0.5 扣 5，> 0.7 扣 10 |

公式：`Score = (30 + 20 + 15 + 15 + 10) - 10 = 100 上限`，实际是各因子加权和。

## 第三层：冷却 + 推送阈值

| 分数区间 | 级别 | 推送策略 | 冷却时间 |
|---|---|---|---|
| ≥75 | 🔴 HIGH | 立即推送 | 15 分钟 |
| 65-74 | 🟡 MEDIUM | 聚合推送 | 30 分钟 |
| 55-64 | 🔵 OBSERVE | 入观察池，不推送 | — |
| <55 | 丢弃 | 不推送，不记录 | — |

冷却时间动态绑定分数：高分币趋势强，冷却短。

## 数据获取流程

```
trending 榜单 → 硬过滤 ← token security (并行)
    ↓ 通过
token info (聪明钱明细) → 评分计算
    ↓ 有信号
发送 TG（附带分数 + 因子明细）
```

## 配置项（新增）

```python
scanner_min_liquidity: float = 50_000.0
scanner_max_rug_risk: float = 0.8
scanner_max_bundler_rat_ratio: float = 0.7
scanner_score_high_threshold: int = 75
scanner_score_medium_threshold: int = 65
scanner_score_low_threshold: int = 55
scanner_cooldown_high_seconds: int = 900
scanner_cooldown_medium_seconds: int = 1800
```

## TG 消息格式

```
🔴 [85] SOL 1m — $PEPE

📊 评分明细
  聪明钱领先: 28/30 (smart_degen 8→23)
  排名加速:  18/20 (#42→#15)
  成交量质量: 12/15 (vol/liquid=2.3x)
  结构健康度: 13/15
  多时间帧:  10/10 (1m+1h)
  风险折价:  -4

地址: 0xabc…def
价格: $0.0123
市值: $1.2M
```

## 文件变更

| 文件 | 变更 |
|---|---|
| `src/scanner/models.py` | 新增 `ScoredToken`, `FilterResult`, `TokenRisk` 模型 |
| `src/scanner/gmgn_client.py` | 新增 `fetch_token_info`, `fetch_token_security` |
| `src/scanner/detector.py` | 替换为两层评分引擎 |
| `src/scanner/notifier.py` | 更新消息格式 |
| `src/scanner/orchestrator.py` | 插入评分 + 冷却逻辑 |
| `src/shared/config.py` | 新增配置项 |
