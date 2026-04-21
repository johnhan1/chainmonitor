# Ingestion 数据源架构彻底重构 Spec

## Why
当前 `DexScreenerSourceStrategy` 同时承担编排流程、上游适配、韧性控制与数据转换，导致新增第二数据源时需要复制大段逻辑，扩展成本高且风险大。需要一次性完成分层重构，建立可复用的多数据源接入骨架，并明确不保留中间兼容层。

## What Changes
- 将现有重逻辑策略拆分为：模板流程层、数据源适配层、韧性 HTTP 执行层、质量策略层。
- 新增统一中间模型 `NormalizedPair`，所有实时数据源先映射到统一模型，再转换为 `MarketTickInput`。
- `DexScreenerSourceStrategy` 改为薄封装策略，内部仅负责装配 adapter/client/policy。
- 新增 `SecondSourceStrategy` 与 `SecondSourceAdapter`，接入同一模板流程。
- 保留并复用 `resilience/controls.py` 中的令牌桶与熔断器原语，不重复实现。
- 保留 `ChainIngestionService -> SourceStrategyFactory -> FallbackSourceChain` 对外主链路与调用方式。
- 删除旧版 `DexScreenerSourceStrategy` 中已迁移的重复逻辑，不保留中间兼容适配代码。
- **BREAKING**：策略内部模块边界与类职责重排，依赖旧私有方法（如 `_request_json*`）的内部调用方将失效。
- **BREAKING**：`SourceStrategyFactory` 的策略注册表与配置值将扩展为包含第二实时数据源。

## Impact
- Affected specs: 多数据源接入能力、采集韧性能力、行情标准化能力、主备补齐能力
- Affected code: `src/ingestion/strategies/`、`src/ingestion/factory/`、`src/ingestion/contracts/`、`src/ingestion/fallback/`、`src/ingestion/services/`、`src/ingestion/resilience/`、`src/shared/config.py`、`tests/`

## ADDED Requirements
### Requirement: 统一模板流程与适配器分层
系统 SHALL 提供统一的实时采集模板流程，任何实时数据源通过 `ProviderAdapter` 接口接入，不得在具体策略中重复实现完整采集主流程。

#### Scenario: 新增第二数据源
- **WHEN** 开发者新增一个实时数据源
- **THEN** 仅需实现该源 adapter 与薄策略装配，不需要复制 DexScreener 的主流程代码

### Requirement: 统一韧性请求执行层
系统 SHALL 提供统一的 `ResilientHttpClient`，集中处理超时、重试、限流、熔断、缓存与请求级指标。

#### Scenario: 上游接口不稳定
- **WHEN** 上游出现 429/5xx/超时
- **THEN** 请求执行层按统一策略进行限流、退避重试与熔断保护，并输出一致指标与日志

### Requirement: 统一中间模型与质量门禁
系统 SHALL 将不同来源数据先归一到 `NormalizedPair`，再通过统一质量策略过滤后转换为 `MarketTickInput`。

#### Scenario: 第二源字段命名与 DexScreener 不一致
- **WHEN** 第二源返回异构字段
- **THEN** adapter 完成字段映射，模板层无需修改即可复用统一过滤与转换逻辑

## MODIFIED Requirements
### Requirement: 实时策略职责边界
实时策略实现 SHALL 仅承担装配职责（adapter/client/policy + chain 上下文），不再承载完整网络请求与数据编排细节。

### Requirement: 工厂注册与模式切换
`SourceStrategyFactory` SHALL 支持实时双源注册，并继续通过 `live/mock/hybrid` 产出 `FallbackSourceChain`，确保 `ChainIngestionService` 对外接口不变。

## REMOVED Requirements
### Requirement: 单策略内聚合所有职责
**Reason**: 该模式导致代码过重、重复与扩展困难，不符合多数据源演进需求。
**Migration**: 将旧策略中的请求、解析、过滤、转换逻辑分别迁移到 `ResilientHttpClient`、`ProviderAdapter`、`PairQualityPolicy` 与模板策略层，完成后删除旧私有实现。
