# `.\scripts\dev.ps1 -Command all` 执行流程详解

本文档详细梳理了在执行 `.\scripts\dev.ps1 -Command all` 时，系统底层依次调用的脚本及执行的具体过程。

## 整体流程概述

当执行 `-Command all` 时，[dev.ps1](file:///d:/Code/chainmonitor/scripts/dev.ps1) 会按照以下顺序依次执行相关操作：

1. 环境初始化 (`setup.ps1`)
2. 启动 Docker 服务 (`docker compose up`)
3. 数据库迁移 (`db-upgrade.ps1`)
4. 执行一次 BSC 管道任务 (`bsc-run-once.ps1`)
5. 代码检查与测试 (`check.ps1`)
6. 冒烟测试 (`smoke.ps1`)

---

## 详细步骤拆解

### 1. 环境初始化：`.\scripts\setup.ps1`
此步骤负责配置本地 Python 虚拟环境和开发依赖：
- 检查并创建 `.venv` 虚拟环境。
- 校验 Python 版本（要求 3.11 或 3.12）。
- 升级 `pip` 并安装 `requirements\dev.txt` 中的开发依赖。
- 如果当前是 Git 仓库，则自动安装 `pre-commit` 钩子。

### 2. 启动 Docker 服务
执行命令：`docker compose -f deploy\docker-compose.yml up -d --build`
- 使用全量配置 (`docker-compose.yml`) 以后台模式启动项目依赖的所有容器，并在启动前重新构建镜像。

### 3. 数据库结构升级：`.\scripts\db-upgrade.ps1`
此步骤负责将数据库更新到最新状态：
- 调用虚拟环境中的 Alembic 工具。
- 执行 `alembic upgrade head`，将数据库表结构和数据迁移至最新版本（Head revision）。

### 4. 执行单次 BSC 数据流：`.\scripts\bsc-run-once.ps1`
此步骤用于测试或触发一次业务管道：
- 调用 Python 代码 `src.app.services.bsc_pipeline.BscPipelineService`。
- 执行 `run_once()` 方法并打印输出其结果（以模型 Dump 的形式），确保业务数据流转正常。

### 5. 代码质量检查与单元测试：`.\scripts\check.ps1`
此步骤用于保证代码库质量：
- 使用 `ruff` 执行静态代码分析 (`ruff check src tests`)。
- 执行 `pytest -q` 跑一遍所有单元测试。
- 如果环境支持，最后执行 `pre-commit run --all-files` 跑一遍全量代码的 pre-commit 钩子检查（如格式化、安全扫描等）。

### 6. 冒烟测试（健康检查）：`.\scripts\smoke.ps1`
最后一步，通过 HTTP 请求对已启动的服务进行存活检测（Smoke Test）：
- 验证后端服务存活：`http://localhost:8000/healthz`
- 验证后端指标接口：`http://localhost:8000/metrics`
- 验证 Prometheus/监控组件：`http://localhost:9090/-/healthy`
- 验证前端/API服务存活：`http://localhost:3000/api/health`
- 如果有任何一个接口未返回 2xx 状态码，流程将抛出异常并报错终止。

---

## 总结
`dev.ps1 -Command all` 是一键式的集成脚本，涵盖了从环境准备、容器启动、数据库初始化、业务跑通、代码质量校验到最终系统连通性测试的完整开发测试生命周期。
