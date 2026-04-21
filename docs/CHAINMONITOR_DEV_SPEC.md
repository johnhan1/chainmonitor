# ChainMonitor 统一开发规范（Full）

## 1. 目标
- 统一多模型代码风格与工程行为。
- 保证可维护、可观测、可回滚、可交付。

## 2. 规则优先级
1. 用户明确需求（功能目标）
2. Hard Rules（强约束）
3. Soft Guidelines（建议）
4. 历史实现风格（参考）

冲突处理：
- 若功能需求与 Hard Rules 冲突：停止并说明冲突点，给出可选方案，不可直接越规实现。

## 3. Hard Rules（强约束）
### 3.1 架构分层
- `app` 路由层不落业务逻辑。
- 编排进 `app/services`。
- 源数据进 `ingestion`，特征进 `feature`，评分进 `scoring`。
- DB 统一 `shared/db`，禁止跨层直接 SQL。
- 契约模型统一 `shared/schemas`。

### 3.2 配置
- 新配置必须进入 `Settings`，统一 `CM_`。
- 禁止业务代码直接 `os.getenv`。
- 默认值需可本地启动；生产敏感配置需显式校验。

### 3.3 执行环境
- 项目内所有 Python 相关操作统一使用 `.venv`，禁止使用全局 Python/全局 pip。
- 执行任何项目 Python 操作前，必须先执行 `Test-Path .\.venv\Scripts\python.exe` 并保留结果。
- 若检查结果为 `False`，必须停止执行，不得 fallback 到全局 Python/pip。
- Python 命令仅允许 `.\.venv\Scripts\python -m <module> ...` 形式。
- 禁止执行未绑定 `.venv` 的命令：`pip ...`、`python ...`、`python -m pip ...`。
- 需要安装单个依赖时，必须先检查 `.venv` 内是否已安装（`python -m pip show <package>`）；仅在未安装时再执行安装。
- 若声称“无 .venv”或“无法使用 .venv”，必须提供 `Test-Path` 与 `Get-Item` 结果作为证据。

### 3.4 错误处理
- 统一错误语义：4xx 参数/权限，502 上游依赖，500 未预期。
- 错误日志必须可追踪（`trace_id`、`chain_id`、动作、原因）。
- 禁止 `except Exception: pass`。

### 3.5 稳定性
- 外部 I/O 必须超时。
- 高风险路径（回放/调度/批处理）必须并发保护。
- 缓存必须 TTL + 上限。
- 阻塞任务用 `asyncio.to_thread` 隔离。

### 3.6 数据与迁移
- 结构变更必须 Alembic。
- migration 必须可升级、可回滚、可重复执行。
- 数据写入应幂等（冲突更新策略明确）。

### 3.7 质量门禁
- 代码需通过 `ruff`、`pytest`。
- 运行链路改动需通过 smoke。
- 所有检查与测试必须在项目 `.venv` 中执行，禁止依赖全局 Python/全局 pip。
- 门禁未通过视为任务未完成。

`.venv` 执行示例（PowerShell）：

```powershell
# 先校验 .venv（必须）
Test-Path .\.venv\Scripts\python.exe
Get-Item .\.venv\Scripts\python.exe

# 安装前先检查（单包场景）
.\.venv\Scripts\python -m pip show pydantic

# 依赖安装
.\.venv\Scripts\python -m pip install -r requirements\dev.txt

# 测试
.\.venv\Scripts\python -m pytest -q

# Lint
.\.venv\Scripts\python -m ruff check src tests

# 可选：格式化检查
.\.venv\Scripts\python -m ruff format --check src tests

# 迁移
.\.venv\Scripts\python -m alembic upgrade head
```

### 3.8 文档联动
- 配置/接口/脚本/监控有变化，必须更新对应层文档。
- 入口变化更新 README，流程变化更新 GUIDE，组件细节更新 DEEP_DIVE。

## 4. Soft Guidelines（建议）
- 小步提交，单次只做一个业务目标。
- 复用现有模式，避免新建平行实现。
- 保持函数短小、边界清晰、命名可读。
- 新增注释只解释“为什么”，不解释显然代码。

## 5. 变更类型 -> 必做动作矩阵
- 新增接口：补 API 测试、错误路径、文档接口说明。
- 改配置：补 Settings + `.env.*.example` + 文档。
- 改 ingestion：补超时/重试/熔断测试或回归用例。
- 改 DB：补 migration + migration 测试。
- 改 pipeline/replay/scheduler：补并发/限流/窗口边界测试。

## 6. Agent 输出模板（强制）
每次任务结束必须输出：
1. 变更文件列表
2. 设计说明（为何这样改）
3. 合规自检（Hard Rules 逐项）
4. 测试执行结果
5. 剩余风险与后续建议

## 7. 禁止项
- 绕过分层直接互调。
- 绕过 Repository 直接 SQL（除 `shared/db`）。
- 无超时外部调用。
- 无 migration 的 schema 改动。
- 使用全局环境安装依赖或执行任何项目 Python 操作（脚本、迁移、lint、测试、服务启动）。
- 单包依赖安装时，未先在 `.venv` 执行 `pip show` 检查即直接安装。
- 使用 `LS` 结果判定 `.venv` 存在性，且未给出 `Test-Path` / `Get-Item` 检查证据。
- 未补最小测试即宣称完成。

## 8. 完成定义（DoD）
- 功能符合需求。
- Hard Rules 全满足。
- 质量门禁通过。
- 必要文档更新完成。
- 无已知高风险未披露项。
