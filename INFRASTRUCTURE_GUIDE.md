# ChainMonitor 框架与基础设施完整上手文档

> 说明：本文是第 2 层文档（框架层）。
> 如果你需要按组件逐项查看部署细节、运维动作、排障矩阵，请继续阅读第 3 层文档：`INFRASTRUCTURE_DEEP_DIVE.md`。

本文档面向第一次接触本项目的同学，目标是让你在不了解历史背景的情况下，依然可以：

- 正确初始化开发环境
- 一键启动/关闭完整基础设施
- 正确执行数据库迁移
- 完成本地质量检查与烟雾测试
- 理解每个组件在整个系统里的作用
- 在常见故障场景下快速恢复

---

## 1. 文档适用范围

本文档覆盖的是“框架与基础设施”层，不包含业务策略逻辑实现。

包含内容：

- 项目结构与模块职责
- Python 本地开发环境（`.venv`）规范
- Docker 容器编排（full/lite）
- 数据库迁移链（Alembic）
- 质量门禁（ruff/pytest/pre-commit/CI）
- 监控与告警（Prometheus/Grafana）
- 备份与恢复
- 排障手册

---

## 2. 技术栈与组件清单

### 2.1 语言与基础框架

- Python `3.11` 或 `3.12`
- FastAPI（应用入口）
- Uvicorn（ASGI Server）
- Pydantic Settings（环境配置）
- SQLAlchemy + Alembic（数据库迁移）

### 2.2 基础设施（full 模式）

- App：`cm-app`
- PostgreSQL：`cm-postgres`
- ClickHouse：`cm-clickhouse`
- Redis：`cm-redis`
- MinIO：`cm-minio`
- Prometheus：`cm-prometheus`
- Grafana：`cm-grafana`

### 2.3 基础设施（lite 模式）

- App：`cm-app-lite`
- PostgreSQL：`cm-postgres-lite`
- Redis：`cm-redis-lite`

---

## 3. 项目目录说明（重点）

```text
alembic/                        # Alembic 迁移框架
  env.py
  script.py.mako
  versions/                     # 迁移版本文件

deploy/
  Dockerfile.app               # App 镜像构建文件
  docker-compose.yml           # full 编排（全量基础设施）
  docker-compose.lite.yml      # lite 编排（低成本）

infra/
  monitoring/
    prometheus/
      prometheus.yml           # 抓取配置
      alerts.yml               # 告警规则
    grafana/
      provisioning/
        datasources/           # 数据源自动导入
        dashboards/            # Dashboard Provider
      dashboards/              # 预置 Dashboard JSON

requirements/
  base.txt                     # 运行依赖
  dev.txt                      # 开发依赖（含 test/lint/pre-commit）

scripts/
  dev.ps1                      # 统一命令入口（最重要）
  setup.ps1                    # 初始化 .venv
  check.ps1                    # lint + pytest + pre-commit
  smoke.ps1                    # smoke 检查
  db-upgrade.ps1               # alembic upgrade head
  db-revision.ps1              # 创建新 migration
  db-backup.ps1                # 备份 PostgreSQL
  db-restore.ps1               # 恢复 PostgreSQL

src/
  app/main.py                  # FastAPI 入口，healthz/metrics
  shared/config.py             # 统一配置读取
```

---

## 4. 前置要求（本地机器）

你需要提前安装：

- Python `3.11` 或 `3.12`
- Docker Desktop（需可执行 `docker compose`）
- Git（建议安装，便于 pre-commit 和日常协作）

在 PowerShell 验证：

```powershell
python --version
docker --version
docker compose version
git --version
```

---

## 5. 环境变量体系

### 5.1 环境模板文件

- `.env.example`
- `.env.dev.example`
- `.env.staging.example`
- `.env.prod.example`

建议流程：

1. 复制模板为 `.env`
2. 根据本机/环境实际地址修改
3. 不要提交 `.env` 到仓库

### 5.2 配置读取机制

配置在 `src/shared/config.py` 中通过 `Settings` 统一读取，使用前缀 `CM_`。

默认加载顺序：

- `.env`
- `.env.{CM_APP_ENV}`

常用变量：

- `CM_APP_ENV`
- `CM_POSTGRES_DSN`
- `CM_REDIS_URL`
- `CM_CLICKHOUSE_HTTP_URL`
- `CM_MINIO_ENDPOINT`

---

## 6. 一键命令入口（推荐）

核心入口：`scripts/dev.ps1`。

支持命令：

- `init`：初始化本地 `.venv` 并安装依赖
- `up`：启动 full 基础设施
- `up-lite`：启动 lite 基础设施
- `down`：停止 full/lite 编排
- `reset`：删除卷并重建 full 环境
- `migrate`：执行 `alembic upgrade head`
- `check`：代码质量检查（含代码规范和测试）
- `smoke`：基础服务可达性检查
- `backup`：PostgreSQL 备份
- `restore`：PostgreSQL 恢复
- `status`：查看 full 编排状态
- `all`：完整一键流程（推荐首轮使用）

---

## 7. 新人第一次上手（标准流程）

在项目根目录执行：

```powershell
.\scripts\dev.ps1 -Command all
```

该命令会按顺序执行：

1. `setup.ps1`：创建并校验 `.venv`，安装依赖
2. `docker compose up -d --build`（full）
3. `db-upgrade.ps1`：迁移到最新版本
4. `migration-check.ps1`：迁移链回滚/重放校验
5. `check.ps1`：ruff + pytest + pre-commit
6. `smoke.ps1`：访问 healthz/metrics/prometheus/grafana

---

## 8. Full / Lite 模式区别

### 8.1 Full 模式（推荐默认）

命令：

```powershell
.\scripts\dev.ps1 -Command up
```

适用场景：

- 日常开发
- 联调
- 监控看板与告警验证
- 本地“接近生产”的基础设施模拟

### 8.2 Lite 模式（低成本）

命令：

```powershell
.\scripts\dev.ps1 -Command up-lite
```

适用场景：

- 只想跑基础 API + 最小依赖
- 机器资源紧张
- 快速验证脚本或基础接口

---

## 9. 服务端口清单

- App：`8000`
- PostgreSQL：`5432`
- ClickHouse HTTP：`8123`
- ClickHouse Native：`9000`
- Redis：`6379`
- MinIO Console：`9001`
- MinIO S3 API：`9002`（映射到容器 9000）
- Prometheus：`9090`
- Grafana：`3000`

---

## 10. 快速健康检查

### 10.1 自动 smoke

```powershell
.\scripts\dev.ps1 -Command smoke
```

### 10.2 手动访问

- `http://localhost:8000/healthz`
- `http://localhost:8000/metrics`
- `http://localhost:9090/-/healthy`
- `http://localhost:3000/api/health`

---

## 11. 数据库迁移规范

### 11.1 当前迁移版本

主要迁移文件位于 `alembic/versions/`，已包含多批次表结构。

### 11.2 升级到最新版本

```powershell
.\scripts\dev.ps1 -Command migrate
```

### 11.3 新建迁移

```powershell
.\scripts\db-revision.ps1 -Message "your migration message"
```

建议命名：

- 动词 + 对象 + 意图，例如：`add_trade_signal_status_index`

---

## 12. 质量门禁

### 12.1 本地检查

```powershell
.\scripts\dev.ps1 -Command check
```

包含：

- ruff 静态检查
- pytest
- pre-commit 全文件检查（当本地有 git）

### 12.2 CI 检查链路

CI（`.github/workflows/ci.yml`）执行顺序：

1. 安装依赖
2. Lint
3. Test
4. Smoke（启动 uvicorn 后请求 healthz/metrics）

---

## 13. 可观测性说明

### 13.1 指标采集

应用暴露 `/metrics`，当前示例指标：

- `cm_http_requests_total`

### 13.2 Prometheus

- 抓取自己：`prometheus:9090`
- 抓取应用：`app:8000/metrics`
- 告警规则：`infra/monitoring/prometheus/alerts.yml`

### 13.3 Grafana

- 数据源自动导入：Prometheus
- Dashboard Provider 自动加载：
  - Provider 配置：`infra/monitoring/grafana/provisioning/dashboards/dashboard.yml`
  - Dashboard JSON：`infra/monitoring/grafana/dashboards/chainmonitor-overview.json`

---

## 14. 备份与恢复（PostgreSQL）

### 14.1 备份

```powershell
.\scripts\dev.ps1 -Command backup
```

默认输出目录：`.\backups`，文件名格式：`chainmonitor_YYYYMMDD_HHMMSS.sql`

### 14.2 恢复

```powershell
.\scripts\dev.ps1 -Command restore -BackupFile .\backups\chainmonitor_YYYYMMDD_HHMMSS.sql
```

脚本会自动识别运行中的 postgres 容器（full/lite）。

---

## 15. 常见故障与处理

### 15.1 `.venv` Python 版本不符合要求

现象：`Unsupported .venv Python version`

处理：

1. 删除 `.venv`
2. 指定版本重建：

```powershell
.\scripts\setup.ps1 -Python "py -3.11"
```

### 15.2 端口占用（5432/6379/8000 等）

现象：compose 启动失败，提示端口冲突。

处理：

1. 查占用进程并关闭
2. 或调整 `docker-compose*.yml` 映射端口
3. 再执行 `.\scripts\dev.ps1 -Command up`

### 15.3 迁移失败

先做定位：

```powershell
.\scripts\dev.ps1 -Command migrate-check
```

常见原因：

- 迁移文件顺序/依赖错误
- downgrade 未覆盖新增对象
- 某迁移依赖了非通用方言特性

### 15.4 smoke 失败

先看状态：

```powershell
.\scripts\dev.ps1 -Command status
docker compose -f deploy\docker-compose.yml logs --tail=200
```

优先看 `app`、`prometheus`、`grafana` 三个容器日志。

---

## 16. 推荐开发日常流程

每天开始：

```powershell
.\scripts\dev.ps1 -Command up
.\scripts\dev.ps1 -Command migrate
.\scripts\dev.ps1 -Command check
```

提交前：

```powershell
.\scripts\dev.ps1 -Command check
.\scripts\dev.ps1 -Command smoke
```

收工：

```powershell
.\scripts\dev.ps1 -Command down
```

---

## 17. 基础设施完成标准（Infra DoD）

满足以下条件，即认为基础设施可交付：

- `.\scripts\dev.ps1 -Command all` 在干净环境可通过
- full/lite 均可启动
- healthz/metrics/prometheus/grafana 可访问
- CI 全链路通过
- 备份与恢复脚本可执行

---

## 18. 新同学 30 分钟上手清单

1. 安装 Python + Docker + Git
2. 执行 `.\scripts\dev.ps1 -Command all`
3. 打开 `healthz`/`metrics`/Prometheus/Grafana
4. 阅读 `scripts/dev.ps1` 理解命令入口
5. 跑一次 `backup` 和 `restore`（可选）

完成以上步骤后，你已经可以在该项目上开始正式开发。

---

## 19. 你最常用的 4 条命令

```powershell
.\scripts\dev.ps1 -Command all
.\scripts\dev.ps1 -Command up
.\scripts\dev.ps1 -Command check
.\scripts\dev.ps1 -Command down
```
