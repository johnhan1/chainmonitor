# Tasks

* [ ] Task 1: 建立系统基线与配置治理

  * [ ] SubTask 1.1: 明确分层边界与模块责任（app/services、ingestion、feature、scoring、shared/db、schemas）

  * [ ] SubTask 1.2: 在 `Settings` 补齐多链、数据源、SLO、回测与模拟实盘核心配置（统一 `CM_` 前缀）

  * [ ] SubTask 1.3: 统一错误响应与 trace\_id 传递规范，补关键日志与指标基础埋点

* [ ] Task 2: 完成核心数据模型与数据库落地

  * [ ] SubTask 2.1: 建立 `chains/tokens/pairs_pools/market_ticks/*_features/token_scores` 核心表与索引分区

  * [ ] SubTask 2.2: 建立 `candidate_pool_snapshots/trade_signals/paper_orders/paper_positions` 交易与模拟表

  * [ ] SubTask 2.3: 建立 `backtest_runs/backtest_metrics/strategy_versions/data_source_health` 治理表

  * [ ] SubTask 2.4: 为所有结构变更提供可回滚 Alembic migration 与基础数据字典文档

* [ ] Task 3: 实现多链接入与标准化主链路（MVP）

  * [ ] SubTask 3.1: 接入 `SOL/BASE/BSC/ETH` 基础行情与池子数据，支持主备源切换

  * [ ] SubTask 3.2: 实现统一标准化模型与实体去重，输出可直接用于特征计算的数据流

  * [ ] SubTask 3.3: 建立数据质量监控（完整率/新鲜度/一致性）与降级策略

* [ ] Task 4: 实现因子计算、Gate 与评分引擎

  * [ ] SubTask 4.1: 落地 v1 因子字典（F001-F015）与计算频率策略

  * [ ] SubTask 4.2: 实现 `Gate-1/2/3` 与 `Alpha/RiskPenalty/FinalScore/Conviction` 计算链路

  * [ ] SubTask 4.3: 产出 A/B/C 候选池、原因码与信号解释字段

* [ ] Task 5: 构建统一事件模型与回测引擎 MVP

  * [ ] SubTask 5.1: 实现统一事件总线与事件持久化结构

  * [ ] SubTask 5.2: 实现事件驱动回测（1m 主回测 + 5m 稳健性复核）

  * [ ] SubTask 5.3: 实现链别成本模型（gas/滑点/fee/延迟/失败概率）与防未来函数约束

* [ ] Task 6: 构建模拟实盘与组合风控

  * [ ] SubTask 6.1: 复用回测撮合与成本函数实现模拟实盘执行

  * [ ] SubTask 6.2: 实现仓位上限、链别风险预算、同叙事集中度约束与风险告警

  * [ ] SubTask 6.3: 生成实盘日报（PnL/回撤/偏差/失败样本标签）

* [ ] Task 7: 构建策略进化、版本治理与灰度发布

  * [ ] SubTask 7.1: 实现每周参数微调任务（权重/阈值/链别参数）

  * [ ] SubTask 7.2: 实现版本评估门禁（收益提升但回撤恶化拒绝发布）

  * [ ] SubTask 7.3: 实现 `10% -> 50% -> 全量` 灰度与自动回滚

* [ ] Task 8: 打通接口、可观测性与验收闭环

  * [ ] SubTask 8.1: 交付最小 API 契约（评分触发、候选池查询、回测任务、版本查询、模拟注入）

  * [ ] SubTask 8.2: 补齐监控看板与告警（延迟、缺失、故障切换、收益风险指标）

  * [ ] SubTask 8.3: 完成端到端测试与 DoD 验收（PF/Expectancy/MaxDD/可解释可回放）

  * [ ] SubTask 8.4: 同步 README/GUIDE/DEEP\_DIVE，形成运维与迭代手册

# Task Dependencies

* Task 2 depends on Task 1

* Task 3 depends on Task 1 and Task 2

* Task 4 depends on Task 3

* Task 5 depends on Task 2 and Task 4

* Task 6 depends on Task 5

* Task 7 depends on Task 6

* Task 8 depends on Task 3, Task 4, Task 5, Task 6, and Task 7
