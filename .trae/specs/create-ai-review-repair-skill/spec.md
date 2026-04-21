# 自动代码审查与修复 Skill Spec

## Why
当前 AI 写码后缺少统一、可量化、可收敛的自动审查闭环，容易出现反复修改但无明确停止边界。需要将“生成-审查-修复-复审”固化为可复用 Skill，提升质量一致性与交付效率。

## What Changes
- 新增一个可复用 Skill，编排 AI 代码生成后的自动审查与定向修复循环。
- 定义硬门禁（必须通过）与软评分（质量分）双层停止机制。
- 定义结构化反馈格式，确保 AI 每轮修复可定位、可验证、可追踪。
- 定义最大迭代次数、无改进终止与人工升级策略，防止死循环。
- 约束 Skill 只做“编排与决策”，具体检查由 CI 工具链执行。

## Impact
- Affected specs: 代码质量治理能力、自动化交付能力、风险控制能力
- Affected code: `.trae/skills/`（新增 Skill 文档）、CI 配置与质量门禁脚本（后续实现）

## ADDED Requirements
### Requirement: 自动审查修复闭环编排
系统 SHALL 提供一个 Skill，按“生成补丁 -> 自动审查 -> 结构化反馈 -> AI 定向修复 -> 复审”执行循环，并在达标时停止。

#### Scenario: 单轮通过
- **WHEN** 首轮审查结果全部通过硬门禁
- **THEN** Skill 立即停止并输出“通过状态 + 检查摘要”

#### Scenario: 多轮修复后通过
- **WHEN** 首轮存在失败项但后续修复达到门禁和阈值
- **THEN** Skill 在达标轮停止，并输出“问题闭环记录 + 最终通过状态”

### Requirement: 可量化停止边界
系统 SHALL 定义并执行停止边界：硬门禁全部通过、软评分达到阈值、或达到最大迭代次数触发终止。

#### Scenario: 达到通过阈值
- **WHEN** 硬门禁全通过且质量分大于等于阈值
- **THEN** Skill 结束循环并标记为成功

#### Scenario: 达到迭代上限
- **WHEN** 循环次数达到上限或连续两轮无显著改进
- **THEN** Skill 停止自动修复并升级为人工审查

### Requirement: 结构化反馈与可追踪输出
系统 SHALL 使用统一结构化反馈格式（如 issue_id、severity、rule、file、evidence、expected_fix、acceptance_criteria）驱动修复。

#### Scenario: 审查失败项反馈
- **WHEN** 任一检查失败
- **THEN** Skill 输出结构化问题清单，并仅允许 AI 修复失败项相关代码

## MODIFIED Requirements
### Requirement: 质量检查执行方式
现有质量检查能力 SHALL 从“人工分散触发”扩展为“Skill 统一编排触发 + 结果汇总输出”。

## REMOVED Requirements
### Requirement: 无明确终止条件的自动修复流程
**Reason**: 无停止边界会导致循环不可控、资源消耗过高、质量不可审计。
**Migration**: 统一迁移到“硬门禁 + 软评分 + 迭代上限 + 人工升级”机制。
