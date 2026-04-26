# Ingestion 开发方向（基于当前讨论）

本文档汇总最近几轮讨论，给出 `chainmonitor` 采集与信号体系的目标方向、分阶段改造路线与落地边界。

---

## 1. 共识结论

1. `ingestion` 的职责应收敛为：**采集 + 标准化 + 原始行情落库**。
2. 异动检测、扫链发现、告警属于**信号层**，应从数据库读取历史窗口进行分析，不应与采集强耦合。
3. 当前 `symbol` 配置采集本质是 watchlist 监控，不是主动发现引擎。
4. 要实现“主动发现 alpha”，需新增 discovery/signal 子系统；但短期可先把 watchlist 监控做强。

---

## 2. 目标架构

## 2.1 分层职责

- `L0 Ingestion（数据供给层）`
  - 输入：watchlist 目标集
  - 处理：多源采集、韧性控制、质量过滤、标准化
  - 输出：`MarketTickInput` 持久化到 `market_ticks`
- `L1 Feature（历史特征层）`
  - 输入：`market_ticks` 历史窗口
  - 处理：滚动窗口因子、相对分位、zscore、趋势加速度
  - 输出：`onchain_flow_features` / `risk_features`
- `L2 Signal（信号决策层）`
  - 输入：特征 + 历史统计
  - 处理：异动检测、评分、分层、冷却、防抖
  - 输出：`token_scores` / `candidate_pool_snapshots` / `signal_events`
- `L3 Alert（告警分发层）`
  - 输入：信号事件
  - 处理：去重、路由、渠道发送、告警审计
  - 输出：Webhook/IM/邮件/控制台等

## 2.2 当前代码映射

- 现有 `ingestion` 已具备多源采集和韧性执行器。
- 现有 `pipeline` 仍是“采集->特征->评分->候选->统一落库”的单链路模式，建议逐步解耦为上面的分层形态。

---

## 3. Watchlist 模块设计（重点）

## 3.1 为什么必须独立 watchlist

当前 `get_chain_symbols()` 属于静态配置清单，不利于：

- 动态增删资产
- 分层采集优先级
- 容量预算和降级
- 命中/淘汰审计

## 3.2 建议的 watchlist 子模块

- `watchlist/models.py`
  - `WatchlistItem(chain_id, symbol, address, priority, tier, status, source, tags, expires_at, last_seen_at, added_reason)`
- `watchlist/repository.py`
  - CRUD、按链批量读取、按优先级分页
- `watchlist/selector.py`
  - 每分钟选择当轮采集集合（A/B/C 分层 + 配额）
- `watchlist/resolver.py`
  - symbol/address 对齐、合法性校验、去重
- `watchlist/policy.py`
  - 容量上限、过期淘汰、冷却策略
- `watchlist/audit.py`
  - 记录加入/移除/提升/降级原因

## 3.3 输入与输出边界

- Ingestion 输入不再直接依赖固定 `CM_*_DEFAULT_SYMBOLS`
- 改为：`WatchlistSelector.select(chain_id, ts_minute) -> list[WatchlistItem]`
- Ingestion 输出仍统一 `MarketTickInput`

---

## 4. 采集容量与性能治理

## 4.1 关键风险

- watchlist 扩大后，单分钟预算不足，采集会超时或覆盖率下降。
- 多源补齐路径中，symbol 搜索调用成本高于地址直查，易成为瓶颈。

## 4.2 预算化采集策略

- 按 `chain + provider` 维护 `request_budget_per_minute`
- 建立每类请求成本模型：
  - 地址批量请求成本低
  - symbol 搜索请求成本高
- 每轮按优先级消耗预算：
  - 先采 `required + A-tier`
  - 再采 `B-tier`
  - 最后 `C-tier`

## 4.3 降级规则（必须）

- 当 429/超时/熔断上升时自动降级：
  1. 降低 symbol 搜索并发
  2. 缩小当轮 watchlist 规模
  3. 保留 required symbols 的硬保障

## 4.4 关键监控指标

- ingestion 覆盖率（实际采集数/目标数）
- provider 级 429 率
- provider 级熔断开启占比
- 当轮预算使用率
- 每层 watchlist 命中率（A/B/C）

---

## 5. 信号层改造方向（异动与主动发现）

## 5.1 异动监控（watchlist 内）

- 数据来源：`market_ticks` 历史窗口
- 典型因子：
  - `volume_spike_ratio`
  - `tx_acceleration`
  - `buy_sell_imbalance_trend`
  - `liquidity_delta`
  - `price_zscore`
- 输出：`signal_events`（含 `signal_type`, `score`, `reason_codes`, `cooldown_until`）

## 5.2 主动发现（watchlist 外）

- 新增 `discovery` 扫描任务，按链分页抓取候选池（DexScreener/Gecko/Birdeye）。
- 发现候选先经过硬门槛（流动性、年龄、风险）后再入候选池。
- 高置信候选自动加入 watchlist，并记录来源原因（`source=discovery`）。

---

## 6. 韧性层现状与后续

## 6.1 已完成（当前可用）

- 组件拆分：`rate_limiter/circuit_breaker/retry_policy/singleflight/cache_store/metrics`
- provider 维度指标
- provider+chain 维度限流配置
- provider 维度缓存 key 隔离

## 6.2 后续增强（生产放量前建议）

- 分布式限流（跨多实例共享）
- 分布式熔断状态或共享 backoff guard
- registry TTL/LRU 清理，避免长期内存增长
- Redis client 全局复用与连接治理

---

## 7. 分阶段实施路线图

## Phase 1：职责收敛（低风险）

- 将 ingestion 定位为数据供给层，明确只产出并落 `market_ticks`
- 保留当前 pipeline 但将 feature/scoring 输入改为“可读历史窗口”
- 增加 `INGESTION_COLLECTION_LOGIC_DEEP_DIVE.md` 与本路线文档同步

## Phase 2：Watchlist 模块化

- 新增 watchlist 表与 repository（需 Alembic migration）
- ingestion 从 watchlist 拉取目标集，不再仅依赖固定 symbols 配置
- 实施 A/B/C 分层采集与预算化调度

## Phase 3：信号层独立

- 新增 `SignalService`，从库计算异动并产出 `signal_events`
- pipeline 改造成“可插拔任务编排”，不再强制同步串行

## Phase 4：主动发现

- 新增 discovery 扫链任务
- 与 watchlist 联动（自动加入、自动降级、自动淘汰）

---

## 8. 数据模型建议（增量）

- 新表 `watchlist_items`
  - 唯一键：`(chain_id, token_id)`
  - 字段：priority/tier/status/source/tags/expires_at/last_seen_at
- 新表 `signal_events`
  - 字段：`chain_id, token_id, ts_minute, signal_type, score, reason_codes, cooldown_until, status`
- 新表 `discovery_candidates`
  - 字段：`chain_id, token_id/pair_address, source, discovered_at, quality_score, state`

---

## 9. 配置方向建议

新增（建议）：

- `CM_WATCHLIST_MAX_ITEMS_BY_CHAIN`
- `CM_WATCHLIST_TIER_A_INTERVAL_SECONDS`
- `CM_WATCHLIST_TIER_B_INTERVAL_SECONDS`
- `CM_WATCHLIST_TIER_C_INTERVAL_SECONDS`
- `CM_INGESTION_BUDGET_REQUESTS_PER_MINUTE_BY_PROVIDER_CHAIN`
- `CM_SIGNAL_ANOMALY_SCORE_THRESHOLD_BY_CHAIN`
- `CM_SIGNAL_ALERT_COOLDOWN_SECONDS_BY_CHAIN`

保持已有 provider 限流配置优先级：

`provider+chain > provider > chain > global`

---

## 10. 风险与注意事项

- 不要在策略层直接写 SQL，统一走 `shared/db`。
- watchlist 迁移初期要做双写或只读切换开关，避免断采。
- signal 阈值需要灰度，不可一次性全开告警。
- 先保证 `market_ticks` 覆盖率，再谈“信号精度”。

---

## 11. 最终目标（一句话）

将系统从“配置驱动采集 + 同步打分”升级为“**watchlist 驱动的数据供给层 + 历史上下文信号层 + 主动发现层**”，实现可扩展、可解释、可放量的链上 alpha 监控与告警体系。
