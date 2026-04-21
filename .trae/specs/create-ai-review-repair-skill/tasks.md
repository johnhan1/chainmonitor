# Tasks
- [x] Task 1: 定义 Skill 输入输出契约与停止边界
  - [x] SubTask 1.1: 定义输入参数（代码范围、门禁配置、阈值、最大迭代次数）
  - [x] SubTask 1.2: 定义输出结构（通过状态、问题清单、修复记录、升级状态）
  - [x] SubTask 1.3: 固化停止条件与失败升级规则（含无改进终止）

- [x] Task 2: 实现自动审查编排
  - [x] SubTask 2.1: 接入 lint/type/test/security/架构规则检查步骤
  - [x] SubTask 2.2: 统一聚合检查结果为结构化反馈
  - [x] SubTask 2.3: 输出按严重级排序的问题清单

- [x] Task 3: 实现 AI 定向修复循环
  - [x] SubTask 3.1: 构造“仅修复失败项”的修复提示模板
  - [x] SubTask 3.2: 每轮修复后自动复审并计算质量分变化
  - [x] SubTask 3.3: 达标停止或超限升级人工审查

- [x] Task 4: 接入 CI 与可观测输出
  - [x] SubTask 4.1: 在 CI 中加入 Skill 执行入口与门禁阻断
  - [x] SubTask 4.2: 输出轮次、通过率、失败原因分布等指标
  - [x] SubTask 4.3: 记录审查日志与 trace_id，便于追踪

- [x] Task 5: 验证与回归
  - [x] SubTask 5.1: 补充成功路径测试（门禁通过后立即停止）
  - [x] SubTask 5.2: 补充失败路径测试（迭代上限、无改进、人工升级）
  - [x] SubTask 5.3: 校验不回归（质量分、覆盖率、关键测试集）

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
- Task 5 depends on Task 2, Task 3, and Task 4
