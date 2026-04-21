# `src/ingestion` 目录详解与扩展指南

本文档基于当前仓库实现（`d:\Code\chainmonitor\src\ingestion`）整理，目标是回答三件事：

1. 这个目录整体是干什么的
2. 每个子目录/文件分别负责什么
3. 如何新增数据源、如何新增一条链（详细步骤）

---

## 1. `src/ingestion` 整体职责

`ingestion` 是行情采集层（Market Data Ingestion Layer），负责：

- 按链（`chain_id`）和时间窗口（`ts_minute`）采集行情数据
- 将外部源数据统一转换为内部标准结构 `MarketTickInput`
- 做数据源切换与兜底（Primary/Secondary + Fallback）
- 做采集侧的韧性控制（限流、重试、熔断、缓存、质量门控）

它不是“业务打分/策略决策层”，而是“可靠拿到标准化行情输入”的基础设施层。

---

## 2. 架构模式（先看全局）

当前实现是典型的 **Strategy + Factory + Fallback + Service** 组合：

- `contracts/`：定义采集策略接口与标准异常
- `strategies/`：具体数据源实现（如 DexScreener、GeckoTerminal、Birdeye）
- `factory/`：根据配置装配主/备策略
- `fallback/`：执行主备切换与结果补全
- `services/`：对外统一入口
- `resilience/`：通用韧性组件（令牌桶、熔断器）
- `chain_ingestion_source_base.py`：所有策略共享的基础能力

调用链路：

`ChainIngestionService` -> `SourceStrategyFactory.create(...)` -> `FallbackSourceChain(sources=[s1,s2,s3])` -> `按顺序补齐缺失 token`

---

## 3. 目录与文件逐个说明

> 只列源码文件（忽略 `__pycache__`）

### 3.1 根目录文件

#### `src/ingestion/__init__.py`

- 包导出文件（`__all__`）
- 对外暴露采集层关键类：`ChainIngestionSourceBase`、`SourceStrategyFactory`、`FallbackSourceChain`、`ChainIngestionService`、`DexScreenerSourceStrategy`、`GeckoTerminalSourceStrategy`、`BirdeyeSourceStrategy`

#### `src/ingestion/chain_ingestion_source_base.py`

采集策略基类，提供所有策略共享的通用逻辑：

- 初始化时校验 `chain_id` 是否在配置支持列表里
- 解析链的 symbol 列表（`_symbols()`）
- 统一 token_id 生成规则（`_token_id(symbol)` -> `"{chain}_{symbol}"`）
- 统一分钟时间归一化（UTC，秒和微秒归零）
- 稳定随机种子生成（供一致性哈希与测试场景复用）

这是“策略代码避免重复”的公共底座。

### 3.2 `contracts/`

#### `src/ingestion/contracts/__init__.py`

- 导出契约对象：`SourceStrategy`、`IngestionFetchError`、`ProviderAdapter`、`NormalizedPair`、`PairQualityPolicy`

#### `src/ingestion/contracts/source_strategy.py`

- 定义策略抽象接口 `SourceStrategy`
- 约束所有策略实现 `async fetch_market_ticks(ts_minute) -> list[MarketTickInput]`

#### `src/ingestion/contracts/errors.py`

- 定义采集层统一异常 `IngestionFetchError`
- 包含结构化字段：`reason`、`detail`、`chain_id`、`trace_id`
- 作用：让上层能按原因分类处理错误，而不只是字符串报错

#### `src/ingestion/contracts/provider_adapter.py`

- 定义统一上游适配器契约 `ProviderAdapter`
- 约束实时源适配器提供两类能力：
  - `fetch_pairs_by_addresses(...)`
  - `fetch_pair_by_symbol(...)`
- 作用：把“上游接口差异”封装在 adapter 层，模板策略无需感知源差异

#### `src/ingestion/contracts/normalized_pair.py`

- 定义跨数据源统一中间模型 `NormalizedPair`
- 承载统一字段（symbol、价格、成交量、流动性、买卖笔数、pair 元数据）
- 作用：实时源先归一，再走统一质量门禁与 `MarketTickInput` 转换

#### `src/ingestion/contracts/pair_quality_policy.py`

- 定义质量门禁契约 `PairQualityPolicy`
- 提供默认实现 `DefaultPairQualityPolicy`，覆盖黑名单、最小年龄、换手率等规则
- 作用：质量过滤逻辑独立化，便于多源复用与替换

### 3.3 `factory/`

#### `src/ingestion/factory/__init__.py`

- 导出 `SourceStrategyFactory`

#### `src/ingestion/factory/source_strategy_factory.py`

工厂职责：

- 内置策略注册表 `_registry`（当前有 `dexscreener`、`geckoterminal`、`birdeye`）
- 读取配置：
  - `ingestion_strategy_order`
- 根据注册表按顺序构建策略实例列表
- 装配为 `FallbackSourceChain`
- 启动时校验关键配置合法性：
  - 主备策略名是否受支持
  - 成功率阈值是否在 `[0,1]`
  - 每条支持链的重试/并发/限流/熔断/成功率/最小币对年龄等参数可解析

它是“配置驱动策略组装”的中心点。

### 3.4 `fallback/`

#### `src/ingestion/fallback/__init__.py`

- 导出 `FallbackSourceChain`

#### `src/ingestion/fallback/fallback_source_chain.py`

主备编排器，核心逻辑：

- `data_mode=live` 或 `data_mode=hybrid`：
  - 依次尝试 `sources`（例如 DexScreener -> GeckoTerminal -> Birdeye）
  - 每一层只补齐上一层缺失 token
  - 若补后仍缺 symbol，抛 `incomplete_fallback`
  - 若所有来源都失败且无有效数据，抛 `all_sources_failed`

这个文件实现了“优先真实源 + 自动兜底补齐”的策略。

### 3.5 `resilience/`

#### `src/ingestion/resilience/__init__.py`

- 导出 `AsyncTokenBucket`、`AsyncCircuitBreaker`、`ResilientHttpClient`

#### `src/ingestion/resilience/controls.py`

提供通用韧性组件：

- `AsyncTokenBucket`：异步令牌桶，控制请求速率
- `AsyncCircuitBreaker`：异步熔断器（closed/open/half_open）
  - 达到失败阈值后打开熔断
  - 恢复窗口后进入 half-open 探测
  - 成功后恢复 closed

这是网络不稳定场景下控制放大故障的关键基础件。

#### `src/ingestion/resilience/resilient_http_client.py`

- 提供统一 HTTP 韧性客户端 `ResilientHttpClient`
- 内聚重试、指数退避、熔断、限流、进程内缓存、Redis 缓存、singleflight
- 对 adapter 暴露统一 `get_json(...)` 接口，避免策略层重复实现请求逻辑

### 3.6 `services/`

#### `src/ingestion/services/__init__.py`

- 导出 `ChainIngestionService`

#### `src/ingestion/services/chain_ingestion_service.py`

对外服务入口：

- 构造时通过工厂创建策略链
- 暴露简洁接口 `fetch_market_ticks()`
- 上层调用方无需感知具体数据源、fallback、韧性细节

### 3.7 `strategies/`

#### `src/ingestion/strategies/__init__.py`

- 导出 `BaseLiveSourceStrategy`、`DexScreenerSourceStrategy`、`GeckoTerminalSourceStrategy`、`BirdeyeSourceStrategy`

#### `src/ingestion/strategies/base_live_source_strategy.py`

- 定义实时源模板基类 `BaseLiveSourceStrategy`
- 固化统一流程：采集 -> 质量过滤 -> 转换 `MarketTickInput`
- 依赖注入 `ProviderAdapter` 与 `PairQualityPolicy`，减少新实时源重复代码

#### `src/ingestion/strategies/dexscreener_source_strategy.py`

真实行情采集薄策略（编排层）：

- 数据源：DexScreener HTTP API
- 负责主流程编排：required mapping 校验、地址优先抓取、symbol 补齐、覆盖率校验
- 通过 `BaseLiveSourceStrategy` 统一质量门控与 `MarketTickInput` 构建
- 仅保留策略级可观测性（覆盖率、必需映射缺失），不再直接实现 HTTP 重试/缓存细节

#### `src/ingestion/adapters/dexscreener_provider_adapter.py`

- 实现 `ProviderAdapter`，封装 DexScreener 端点协议与 payload 解析
- 支持两类请求：
  - 地址批量：`/latest/dex/tokens/{address,...}`
  - symbol 搜索：`/latest/dex/search?q=`
- 依赖 `ResilientHttpClient` 执行请求，输出统一 `NormalizedPair`

#### `src/ingestion/adapters/geckoterminal_provider_adapter.py`

- 实现 `ProviderAdapter`，封装 GeckoTerminal v2 API 的端点调用与字段映射
- 支持两类请求：
  - 地址拉取：`/networks/{network}/tokens/{address}/pools`
  - symbol 搜索：`/search/pools?query=...&network=...`
- 输出统一 `NormalizedPair`，与 DexScreener 共用模板策略与质量门禁

#### `src/ingestion/strategies/geckoterminal_source_strategy.py`

- 真实行情采集薄策略（编排层）
- 复用 `BaseLiveSourceStrategy` 的统一转换与过滤逻辑
- 承担 GeckoTerminal 特有的 required mapping、覆盖率、必需 symbol 校验

#### `src/ingestion/strategies/birdeye_source_strategy.py`

兜底实时源策略（第三层）：

- 通过 Birdeye 免费 API 获取 token 行情数据
- 在 DexScreener / GeckoTerminal 覆盖不足时补齐
- 复用统一模板流程、质量门禁和韧性请求层

---

## 4. 配置与 `ingestion` 的关系

`ingestion` 高度依赖 `src/shared/config.py` 中 `Settings`，关键点：

- 支持链集合由 `supported_chains` 给出
- 每条链的 symbol 列表通过 `get_chain_symbols(chain_id)`
- DexScreener 链映射通过 `get_dexscreener_chain_id(chain_id)`
- GeckoTerminal 网络映射通过 `get_geckoterminal_network(chain_id)`
- 可选地址映射通过 `get_chain_token_addresses(chain_id)`
- 数据源顺序通过：
  - `CM_INGESTION_STRATEGY_ORDER`（例如 `dexscreener,geckoterminal,birdeye`）
- 韧性参数通过 `CM_MARKET_DATA_*` 及 `*_BY_CHAIN` 覆盖

所以新增链或调整采集行为，绝大部分入口都在配置层。

---

## 5. 如何新增一个“数据源”（详细步骤）

下面以新增 `FooSourceStrategy` 为例。

### 步骤 1：新建策略文件

在 `src/ingestion/strategies/` 新增文件 `foo_source_strategy.py`：

- 类继承：`ChainIngestionSourceBase, SourceStrategy`
- 必须实现：
  - `async fetch_market_ticks(self, ts_minute=None) -> list[MarketTickInput]`
- 输出必须是标准 `MarketTickInput` 列表（不要返回外部源原始 JSON）
- 失败场景请抛 `IngestionFetchError`（带 `reason/detail/trace_id`）

建议遵循现有约定：

- 用 `self._symbols()` 作为目标 token 集
- 用 `self._token_id(symbol)` 统一 token_id
- 用 `self._normalize_ts(ts_minute)` 统一分钟粒度时间

### 步骤 2：更新策略包导出

修改 `src/ingestion/strategies/__init__.py`：

- 导入 `FooSourceStrategy`
- 加到 `__all__`

### 步骤 3：注册到工厂

修改 `src/ingestion/factory/source_strategy_factory.py`：

- 导入 `FooSourceStrategy`
- 在 `_registry` 中注册，比如：
  - `"foo": FooSourceStrategy`

只有注册后，`CM_INGESTION_STRATEGY_ORDER` 才能使用它。

### 步骤 4：配置启用

在 `.env`（或对应环境文件）设置：

- `CM_INGESTION_STRATEGY_ORDER=dexscreener,geckoterminal,foo`

也可以先把它放在末位作为兜底源灰度验证。

### 步骤 5：验证

最低建议验证项：

- `live` 模式：能返回 `MarketTickInput`
- `hybrid/live` 模式：当前层不全时下一层能补齐
- 异常链路：可抛结构化 `IngestionFetchError`
- 指标与日志：是否有足够可观测信息（建议对齐 DexScreener 策略风格）

---

## 6. 如何新增一条链（详细步骤）

这里的“新增链”指系统原生支持一个新 `chain_id`（例如 `arb`）。

### 步骤 1：在 `Settings` 增加链基础字段

修改 `src/shared/config.py`，新增类似字段：

- `arb_chain_id: str = "arb"`
- `arb_default_symbols: str = "..."`
- `arb_strategy_version: str = "arb-mvp-v1"`
- `arb_token_addresses: str = ""`

并在 `supported_chains` 属性中加入 `self.arb_chain_id`。

### 步骤 2：补全链映射函数

在 `src/shared/config.py` 这些方法的 `mapping` 中新增 `arb`：

- `get_chain_symbols`
- `get_strategy_version`
- `get_dexscreener_chain_id`
- `get_chain_token_addresses`

注意：

- `get_dexscreener_chain_id` 必须填 DexScreener 实际识别的链标识（不是随便字符串）
- 若 DexScreener 暂不支持该链，你需要：
  - 新增可用数据源策略（见第 5 节），并
  - 通过主备策略配置避开 DexScreener

### 步骤 3：补充环境变量样例

更新 `.env.example` 及各环境示例文件（如 `.env.dev.example`）：

- `CM_ARB_CHAIN_ID=arb`
- `CM_ARB_DEFAULT_SYMBOLS=...`
- `CM_ARB_STRATEGY_VERSION=arb-mvp-v1`
- `CM_ARB_TOKEN_ADDRESSES=SYMBOL=ADDRESS,...`

如果调度器要跑这条链，还要把 `arb` 加入：

- `CM_PIPELINE_SCHEDULER_CHAINS=...,arb`

### 步骤 4：配置链级参数（可选但推荐）

可按链覆盖采集参数，避免“一刀切”：

- `CM_MARKET_DATA_RETRY_ATTEMPTS_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_MAX_CONCURRENCY_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_RATE_LIMIT_PER_SECOND_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_CIRCUIT_FAILURE_THRESHOLD_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_CIRCUIT_RECOVERY_SECONDS_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_MIN_SUCCESS_RATIO_BY_CHAIN=arb=...`
- `CM_MARKET_DATA_MIN_PAIR_AGE_SECONDS_BY_CHAIN=arb=...`

### 步骤 5：联调验证

建议顺序：

1. `live` 模式验证一级源抓取
2. 验证二级、三级兜底补齐逻辑
3. 观察日志与 Prometheus 指标（成功率、重试、熔断、缺失映射）

---

## 7. 两类扩展的“最小修改面”总结

### 新增数据源（不加新链）

- 必改：
  - `src/ingestion/strategies/<new>_source_strategy.py`（新增）
  - `src/ingestion/strategies/__init__.py`
  - `src/ingestion/factory/source_strategy_factory.py`
- 常改：
  - `.env*` 中 `CM_INGESTION_STRATEGY_ORDER`

### 新增链（可不加新数据源）

- 必改：
  - `src/shared/config.py`（字段 + supported_chains + 各 mapping）
  - `.env*.example`（新增链相关变量）
- 常改：
  - `.env` 实际值（symbols、addresses、按链阈值）
  - 调度链列表 `CM_PIPELINE_SCHEDULER_CHAINS`

---

## 8. 常见坑位

- 只加了链字段，但忘了在 `supported_chains` 和映射函数里登记，会在运行时 KeyError/unsupported。
- 新策略未注册到工厂 `_registry`，配置填了策略名也无法创建。
- `CM_INGESTION_STRATEGY_ORDER` 中的策略名与注册表 key 不一致。
- 新链没有 token 地址映射时，DexScreener 仍可走 symbol 搜索，但覆盖率可能下降，触发 `insufficient_coverage`。
- `CM_MARKET_DATA_MIN_SUCCESS_RATIO` 设得过高会导致多源补齐后仍判定失败；建议按链单独调优。

---

## 9. 一句话结论

`src/ingestion` 的核心价值是：**把多来源行情采集标准化、可兜底、可观测、可配置化**。
扩展时遵循“策略实现放 `strategies`，装配注册放 `factory`，链支持放 `Settings` 映射”的原则即可稳定演进。
