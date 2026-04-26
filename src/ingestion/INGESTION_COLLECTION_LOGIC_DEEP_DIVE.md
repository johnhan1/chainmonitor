# Ingestion 采集逻辑深度说明

本文档基于当前 `src/ingestion` 代码实现，回答以下问题：

1. 当前采集器到底按什么维度采集
2. 是不是全量采集，是否按交易量动态发现
3. 每个数据源（DexScreener / GeckoTerminal / Birdeye）的具体采集与筛选逻辑
4. 质量过滤、回退补齐、最终输出字段是如何计算的

---

## 1. 整体执行链路

对外入口只有 `ChainIngestionService.fetch_market_ticks(ts_minute)`：

1. `ChainIngestionService` 调 `SourceStrategyFactory.create(chain_id)`
2. `Factory` 根据 `CM_INGESTION_STRATEGY_ORDER` 组装策略列表（默认：`dexscreener,geckoterminal,birdeye`）
3. 返回 `FallbackSourceChain(sources=[...])`
4. `FallbackSourceChain` 依次执行每个 source，补齐缺失 token
5. 成功后返回统一结构 `list[MarketTickInput]`

简化时序：

`Service -> Factory -> FallbackChain -> S1 -> S2 -> S3 -> MarketTickInput[]`

---

## 2. 采集维度与“是否全量采集”

### 2.1 采集维度

当前采集是 **按链 + 固定 symbol 清单 + 分钟时间窗口** 采集：

- 链维度：`chain_id`（如 `bsc/base/eth/sol`）
- 资产维度：`Settings.get_chain_symbols(chain_id)` 返回的 symbol 列表
- 时间维度：`ts_minute`（统一归一到 UTC 的分钟粒度）

因此它不是“按交易量实时发现币种”的爬虫模型，而是“**配置驱动的目标清单采集**”。

### 2.2 是否全量采集

“全量”指的是：对当前链配置的 symbol 列表尽量全覆盖。

- 每次执行会遍历该链全部目标 symbols
- 每个 source 都尝试填充这些 symbols 的行情
- `FallbackSourceChain` 会把前一层缺的 token 交给下一层补齐
- 最终仍缺 symbol 会抛 `incomplete_fallback`

结论：

- 对“配置的 symbol universe”是全量采集
- 不是对整条链全部资产全网扫描
- 不是按 volume 排行自动扩容 universe

---

## 3. Universe 如何确定

symbol universe 来自 `Settings.get_chain_symbols(chain_id)`，本质是配置项：

- `CM_BSC_DEFAULT_SYMBOLS`
- `CM_BASE_DEFAULT_SYMBOLS`
- `CM_ETH_DEFAULT_SYMBOLS`
- `CM_SOL_DEFAULT_SYMBOLS`

同时 token 地址映射来自 `Settings.get_chain_token_addresses(chain_id)`（`SYMBOL=ADDRESS,...`）。

地址映射用于“地址优先拉取”，可提升精度与稳定性。

---

## 4. 策略链与补齐机制

`FallbackSourceChain` 的行为是“顺序补齐”：

1. 初始化 `by_token = {}`
2. 遍历 sources（默认 `dexscreener -> geckoterminal -> birdeye`）
3. 每个 source 返回 `source_rows`
4. 用 `setdefault` 写入 `by_token`（先到先得，不覆盖已有 token）
5. 所有 source 结束后检查缺失

关键语义：

- 上游 source 有优先级，后续 source 只兜底补缺
- 如果首源给了某 token，后源不会覆盖它
- 如果所有 source 都失败且一条都没拿到，抛 `all_sources_failed`

---

## 5. 单个实时策略的内部流程

三种实时策略（DexScreener/GeckoTerminal/Birdeye）内部流程一致：

1. 归一化分钟时间 `target_ts`
2. 读取 symbols
3. 读取 `address_map`
4. 计算 `required_address_symbols`
5. 校验 required mapping
6. 先按地址批量拉取
7. 再按 symbol 补齐剩余
8. 校验成功率 `success_ratio`
9. 质量门禁过滤
10. 转成 `MarketTickInput`
11. 校验 required rows

其中 `required_address_symbols` 规则：

- 若配置了 `CM_MARKET_DATA_REQUIRED_ADDRESS_SYMBOLS_BY_CHAIN`，使用其交集
- 否则在生产环境且 `market_data_require_address_mapping_in_production=true` 时，默认要求全部 symbol 必须有地址映射

---

## 6. Provider 适配层的“具体采集逻辑”

## 6.1 DexScreener

### 地址路径（优先）

- API：`/latest/dex/tokens/{address1,address2,...}`
- 分块：每 20 个地址一批
- 并发：受 `market_data_max_concurrency` 控制
- 过滤：只保留当前链 `chainId` 匹配的数据
- 选池：同地址多个池时，按 `liquidity.usd` 最大选 best pair

### Symbol 路径（补齐）

- API：`/latest/dex/search?q={symbol}`
- 候选：`baseToken.symbol == symbol` 且 `chainId` 匹配
- 选池：按 `liquidity.usd` 最大

### 重要点

- DexScreener 的 `volume.m5 / txns.m5` 可直接用 5m 数据

## 6.2 GeckoTerminal

### 地址路径（优先）

- API：`/networks/{network}/tokens/{address}/pools`
- 选池：按 `reserve_in_usd` 最大

### Symbol 路径（补齐）

- API：`/search/pools?query={symbol}&network={network}`
- 候选：network 匹配，且 base token symbol 匹配
- base token 信息会从 `included` 关系对象补全

### 时间窗与交易数换算

- 优先取 `m5`
- 若没有 `m5`，会用 `h1/h6/h24` 做近似换算到 5 分钟
- `transactions` 同理：优先 `m5`，否则 `h1/12`

## 6.3 Birdeye（兜底源）

### 地址路径（优先）

- API：`/v3/token/market-data?address=...&chain=...`

### Symbol 路径（补齐）

1. 先调 `/v3/search?keyword={symbol}&chain=...` 找地址
2. 再调 token market-data

### 5m 数据换算

Birdeye字段偏 24h，所以会做近似换算：

- `volume_5m = volume24h / 288`
- `tx_5m = trade24h / 288`
- buys/sells 约按 1:1 拆分

这意味着 Birdeye 更偏“可用兜底”，5m 精细度弱于前两源。

---

## 7. 质量门禁（不是只看交易量）

采集并不是“拿到就用”，会经过 `DefaultPairQualityPolicy`：

1. DEX 黑名单过滤：`dex_id` 在 `market_data_dex_blacklist_ids`
2. 路由关键词黑名单：`pair_address|url` 命中 `market_data_route_blacklist_keywords`
3. 币对年龄过滤：`pair_created_at_ms` 必须存在，且年龄 >= `min_pair_age_seconds`
4. 价格有效性：`price_usd > 0`
5. 数值合法性：`volume/liquidity/buys/sells` 不得为负
6. 异常换手过滤：`volume_5m / liquidity_usd <= max_volume_liquidity_ratio`

结论：

- 采集决策不以“交易量越大越优先”作为主逻辑
- 交易量只用于生成特征值与门禁中的 volume/liquidity 比例约束

---

## 8. 成功率与硬约束

每个 source 会先做覆盖率检查：

- `success_ratio = len(pairs_by_symbol) / len(symbols)`
- 低于 `market_data_min_success_ratio` 抛 `insufficient_coverage`

另外还有 required symbol 硬约束：

- required symbol 必须有地址映射（`required_mapping_missing`）
- required symbol 必须在地址拉取中解析成功（`required_symbol_unresolved`）
- required symbol 经过质量门禁后仍必须保留（`required_symbol_invalid`）

---

## 9. 输出字段如何构造

最终输出统一 `MarketTickInput`：

- `token_id = "{chain_id}_{symbol.lower()}"`
- `ts_minute` = UTC 分钟
- `price_usd` 直接来自标准化 pair
- `volume_1m = volume_5m / 5`
- `buys_1m = buys_5m / 5`
- `sells_1m = sells_5m / 5`
- `tx_count_1m = (buys_5m + sells_5m) / 5`

说明：

- 这是统一分钟级输入，不同 provider 先归一为 `NormalizedPair` 再转换，保证下游一致。

---

## 10. 韧性编排如何介入采集

每个 provider 都通过 `ResilientHttpClient.get_json()` 发请求，统一具备：

- provider+chain 维度限流（令牌桶）
- endpoint 熔断
- provider 级退避保护
- 重试与 backoff
- singleflight 去重
- 进程内 + Redis 缓存
- provider 维度指标

因此三源策略在“采集业务逻辑”层面统一，但“韧性参数”可按 provider/chain 分别调优。

---

## 11. 直接回答你的问题

1. 按什么维度采集？
按 `chain_id + 配置symbols + ts_minute` 采集。

2. 是全量采集吗？
对“该链配置symbols集合”做全量覆盖采集；不是全网资产发现。

3. 按交易量采集吗？
不是按交易量做 universe 选择。交易量主要用于：
- 选池时的辅助（实际主要按 liquidity）
- 质量门禁中的换手比例
- 输出特征值（volume_1m/5m）

4. 具体逻辑核心是什么？
`地址优先 -> symbol补齐 -> 成功率校验 -> 质量门禁 -> fallback补齐 -> 标准输出`。

---

## 12. 一句话总结

当前采集器是“**配置驱动的目标资产全量覆盖采集器**”，而不是“交易量驱动的全网发现器”；通过三源顺序补齐 + 统一质量门禁 + 韧性请求编排，确保稳定输出分钟级标准行情数据。
