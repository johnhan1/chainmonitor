# ChainMonitor Hard Rules (Short)

你是本仓库编码代理。必须严格遵守以下规则，违反任一条即停止并说明原因，不得继续生成代码。

## A. 分层边界（必须）
1. `src/app/` 仅做路由与 HTTP 映射，不写核心业务逻辑。
2. 业务编排只放 `src/app/services/`。
3. 数据源逻辑只放 `src/ingestion/`；特征只放 `src/feature/`；评分只放 `src/scoring/`。
4. 数据库访问只通过 `src/shared/db/`；禁止在其他层直接写 SQL。
5. 跨层数据结构优先使用 `src/shared/schemas/` 的 Pydantic 模型。

## B. 配置与安全（必须）
6. 所有新配置必须进 `src/shared/config.py::Settings`，统一 `CM_` 前缀。
7. 禁止在业务代码直接 `os.getenv` 读取业务配置。
8. 外部 HTTP 调用必须有超时；高风险接口必须有鉴权/限流保护。

## C. 代码风格（必须）
9. Python 3.11/3.12 兼容；新增模块默认 `from __future__ import annotations`。
10. 完整类型标注；行宽 <= 100；导入顺序遵循 ruff/isort。
11. 命名统一：函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
12. 对外返回结构使用 Pydantic；序列化统一 `model_dump()`。

## D. 稳定性与可观测性（必须）
13. 异常不得吞掉；必须记录日志并转换为一致错误响应（含 `message`、`trace_id`）。
14. 关键路径新增功能时，至少补日志或 Prometheus 指标（推荐两者都补）。
15. 并发/回放/调度路径必须有并发保护与超时边界。

## E. 迁移与测试（必须）
16. 涉及表结构变更必须提供 Alembic migration，且可 upgrade/downgrade。
17. 每次改动至少补 1 条测试；高风险逻辑需成功+失败路径测试。

## F. 执行环境（必须）
18. 执行任何项目 Python 操作前，必须先执行并展示：`Test-Path .\.venv\Scripts\python.exe`。
19. 若第 18 条结果为 `False`，必须停止并说明原因；禁止 fallback 到全局 `python`/`pip` 继续执行。
20. 项目内 Python 命令仅允许：`.\.venv\Scripts\python -m <module> ...` 形式。
21. 禁止执行未绑定 `.venv` 的命令：`pip ...`、`python ...`、`python -m pip ...`。
22. 需要安装单个 Python 依赖时，不得直接执行安装；必须先在 `.venv` 中检查是否已安装（示例：`.\.venv\Scripts\python -m pip show <package>`），仅在未安装时再执行安装。
23. 若声称“无 .venv”或“无法使用 .venv”，必须附带检查证据：`Test-Path .\.venv\Scripts\python.exe` 与 `Get-Item .\.venv\Scripts\python.exe` 结果。

## G. 文档联动（必须）
24. 改配置/脚本/接口/监控时，必须同步更新文档（README 或 GUIDE 或 DEEP_DIVE）。

## H. 输出契约（每次回复必须附带）
25. 输出“变更摘要”：改了哪些文件、做了什么。
26. 输出“合规自检”：逐条回答 6/8/13/16/17/18/19/20/21/22/23/24 是否满足。
27. 若有未满足项，必须明确写“未完成项 + 风险 + 下一步”。
