# ChainMonitor Foundation

当前仓库已完成“基础设施封版”骨架，可直接用于多人并行开发。

## 基础设施范围

- 开发运行时：Python `3.11/3.12` + 本地 `.venv`（禁止全局 `pip install`）
- 容器底座：`app`、`PostgreSQL`、`ClickHouse`、`Redis`、`MinIO`、`Prometheus`、`Grafana`
- 数据迁移：Alembic 多批次迁移（核心表 + 约束 + 批次扩展）
- 工程质量：`ruff`、`pytest`、`pre-commit`、CI smoke
- 可观测性：`/metrics`、Prometheus 抓取、Grafana 预置 dashboard、Prometheus 告警规则
- 运维脚手架：统一命令入口、数据库备份恢复、full/lite 两套 compose

详细文档分层：

- 第 2 层（框架层）：`INFRASTRUCTURE_GUIDE.md`
- 第 3 层（组件深度层）：`INFRASTRUCTURE_DEEP_DIVE.md`

## 一条命令流程

```powershell
.\scripts\dev.ps1 -Command all
```

等价执行：初始化环境 -> 启动 full stack -> 迁移升级 -> lint/test -> smoke。

## 常用命令

```powershell
# 初始化本地 .venv（默认 py -3.12）
.\scripts\dev.ps1 -Command init

# 启动全量基础设施
.\scripts\dev.ps1 -Command up

# 启动低成本模式（app + postgres + redis）
.\scripts\dev.ps1 -Command up-lite

# 升级迁移
.\scripts\dev.ps1 -Command migrate

# 质量检查
.\scripts\dev.ps1 -Command check

# 端到端 smoke
.\scripts\dev.ps1 -Command smoke

# BSC 主链路跑一次（采集->特征->评分->候选池）
.\scripts\dev.ps1 -Command bsc-run-once

# 备份/恢复
.\scripts\dev.ps1 -Command backup
.\scripts\dev.ps1 -Command restore -BackupFile .\backups\chainmonitor_YYYYMMDD_HHMMSS.sql

# 停止/重置
.\scripts\dev.ps1 -Command down
.\scripts\dev.ps1 -Command reset
```

## 访问地址

- App: `http://localhost:8000/healthz`
- Metrics: `http://localhost:8000/metrics`
- BSC Run Once API: `POST http://localhost:8000/pipeline/bsc/run-once`
- BSC Replay API: `POST http://localhost:8000/pipeline/bsc/replay?ts_minute=2026-04-18T12:30:00Z`
- BSC Candidates API: `GET http://localhost:8000/pipeline/bsc/candidates?tier=A&limit=20`
- BSC Runs API: `GET http://localhost:8000/pipeline/bsc/runs?limit=50`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`（`admin/admin`）
- MinIO Console: `http://localhost:9001`

## 迁移版本

- `a1b2c3d4e5f6_create_core_tables.py`（第一批核心表）
- `b2c3d4e5f607_constraints_and_batch2_tables.py`（约束细化 + 第二批）
- `c3d4e5f60718_batch3_tables.py`（第三批）
- `d4e5f6071829_bsc_pipeline_runs.py`（BSC 调度运行状态表）

## 目录结构

```text
deploy/
  Dockerfile.app
  docker-compose.yml
  docker-compose.lite.yml
infra/
  monitoring/
    prometheus/
    grafana/
scripts/
  dev.ps1
  setup.ps1
  check.ps1
  smoke.ps1
  db-upgrade.ps1
  db-revision.ps1
  db-backup.ps1
  db-restore.ps1
alembic/
  env.py
  versions/
src/
  app/
  shared/
```

## 环境模板

- `.env.example`
- `.env.dev.example`
- `.env.staging.example`
- `.env.prod.example`
- `.env`（本地私有，不入库）

## Infra DoD

- 本地 `.\scripts\dev.ps1 -Command all` 可一次通过
- `docker compose -f deploy\docker-compose.yml ps` 全部核心服务健康
- `healthz/metrics/prometheus/grafana` 可访问
- CI 包含 `lint -> tests -> smoke` 全链路
