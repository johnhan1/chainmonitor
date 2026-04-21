# ChainMonitor 全系统开发规划 Spec

## Why
当前已有 `v1.0` 与 `v1.1` 产品定义，但缺少按工程实施顺序、可验收口径与跨模块依赖组织的统一开发规划。需要形成一份可直接驱动研发、量化验证与产品验收的系统级交付规范。

## What Changes
- 定义覆盖 `SOL/BASE/BSC/ETH` 的端到端交付范围：数据接入、标准化、特征、评分、候选池、回测、模拟实盘、进化与可观测性。
- 将 PRD 中“目标/指标/模块”映射为可执行能力域与阶段化交付节奏（M0-M4）。
- 固化统一事件模型与回测/模拟实盘口径一致性要求，避免未来函数与双口径偏差。
- 固化数据库落地优先级：先 `market_ticks/features/token_scores` 核心链路，再扩展回测与版本治理表。
- 固化上线门槛：`PF/Expectancy/MaxDD/容量冲击` 与数据质量 SLO、延迟 SLO。
- **BREAKING**：后续新增策略能力必须遵循“统一事件模型 + 策略版本化 + 可回放”约束，不允许绕过。
- **BREAKING**：评分信号必须通过 Gate 与风险惩罚链路，不允许直接从单因子输出交易信号。

## Impact
- Affected specs: 多链采集能力、评分决策能力、验证闭环能力、策略演进能力、稳定性与成本治理能力
- Affected code: `src/ingestion/`、`src/feature/`、`src/scoring/`、`src/app/services/`、`src/shared/db/`、`src/shared/schemas/`、`src/shared/config.py`、`alembic/`、`tests/`、监控与文档模块

## ADDED Requirements
### Requirement: 端到端多链 Alpha 发现闭环
系统 SHALL 在同一架构下完成多链数据接入、评分产出、候选池管理、回测验证、模拟实盘与策略进化闭环。

#### Scenario: 正常产出候选池
- **WHEN** 实时数据接入正常且因子计算完成
- **THEN** 系统按 Gate + Score 输出 `A/B/C` 候选池并记录可解释原因码

### Requirement: 统一数据与事件契约
系统 SHALL 采用统一事件模型（`MarketTick/FeatureReady/ScoreUpdated/SignalCreated/OrderPlaced/OrderFilled/PositionClosed/RiskAlert`）与统一跨层 schema，保证可回放与跨模块一致性。

#### Scenario: 回测与模拟共用执行链路
- **WHEN** 对同一策略版本执行回测与模拟实盘
- **THEN** 两者使用同一撮合与成本函数，并可量化偏差来源

### Requirement: 评分门控与风险约束
系统 SHALL 强制执行 `Gate-1/2/3`、`FinalScore`、`Conviction` 与风险惩罚链路，禁止跳过安全性与操纵过滤。

#### Scenario: 高风险标的进入评分
- **WHEN** `honeypot_flag=1` 或 `contract_risk_score > R_max`
- **THEN** 标的在 Gate 阶段被拦截，且写入风险标签与拒绝原因

### Requirement: 策略版本治理与灰度回滚
系统 SHALL 所有参数更新以 `strategy_version` 管理，并支持灰度发布与自动回滚。

#### Scenario: 新版本风险恶化
- **WHEN** 新版本在灰度阶段触发回撤阈值
- **THEN** 系统自动回滚至父版本并生成归因记录

### Requirement: SLO 与数据源容灾
系统 SHALL 具备按链定义的信号延迟目标、数据缺失率阈值与多源故障切换机制。

#### Scenario: 主数据源失败
- **WHEN** 主源连续失败达到阈值
- **THEN** 自动切换备用源并记录 `data_source_health` 与告警事件

## MODIFIED Requirements
### Requirement: 验证模块从“离线为主”升级为“离线+在线一致”
验证链路 SHALL 从仅回测指标评估，升级为“回测 + 模拟实盘 + 偏差归因”三位一体，且以统一事件口径为硬约束。

### Requirement: 进化目标与发布门禁
进化目标 SHALL 以“滚动净收益与风险调整收益最大化”为主，并加入回撤恶化拒绝发布规则，不再仅比较收益提升。

## REMOVED Requirements
### Requirement: 模块级孤立交付即视为可上线
**Reason**: 单模块完成无法保证信号可解释、可回放与可验证，易导致线上收益不可复现。
**Migration**: 以 M0-M4 里程碑执行，只有在核心链路、验证一致性与SLO门槛全部达标后进入推广阶段。
