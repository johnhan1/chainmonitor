# ChainMonitor 基础设施深度文档（第三层）

> 文档定位：这是三层文档体系中的第 3 层（最细层），用于“看完即可运维、排障、扩展”。
>
> 三层关系：
>
> - 第 1 层（总览）：`README.md`
> - 第 2 层（框架）：`INFRASTRUCTURE_GUIDE.md`
> - 第 3 层（本文件）：`INFRASTRUCTURE_DEEP_DIVE.md`

---

## 1. 目标与读者

### 1.1 本文档解决的问题

- 新同学不知道每个组件为什么存在、怎么启动、怎么排障
- 开发同学不知道“应该改哪一层配置”
- 运维同学不知道“故障时第一步看哪里”
- 团队缺少统一、可执行的基础设施标准

### 1.2 适用读者

- 后端开发
- 数据工程
- 平台/运维
- 新入项成员（第一周）

---

## 2. 基础设施总拓扑（逻辑）

```text
                        +---------------------+
                        |     Developer       |
                        |  scripts/dev.ps1    |
                        +----------+----------+
                                   |
                                   v
                    +--------------+--------------+
                    |   Docker Compose (full)     |
                    +--------------+--------------+
                                   |
          +------------------------+-------------------------+
          |                        |                         |
          v                        v                         v
   +-------------+        +-----------------+        +--------------+
   |   cm-app    |<------>|   cm-postgres   |        |   cm-redis   |
   | FastAPI     |        | 事务数据/迁移状态|        | 缓存/队列预留 |
   +------+------+        +--------+--------+        +------+-------+
          |                        |                         |
          |                        |                         |
          v                        v                         v
   +--------------+         +-------------+           +-------------+
   | cm-clickhouse|         |  cm-minio   |           |  migrations |
   | 分析型存储预留 |         | 对象存储预留 |           |   alembic   |
   +------+-------+         +------+------+
          |
          v
   +------+-------+      scrape      +------------------+
   | cm-prometheus+----------------->|   cm-app /metrics|
   +------+-------+                  +------------------+
          |
          v
   +------+-------+
   | cm-grafana   |
   | 看板与可视化  |
   +--------------+
```

---

## 3. 配置分层与来源优先级

### 3.1 配置代码入口

- 文件：`src/shared/config.py`
- 类：`Settings`
- 关键特性：
  - 统一 `CM_` 前缀
  - 支持 `.env` + `.env.{CM_APP_ENV}`
  - 启动时缓存（`@lru_cache`）

### 3.2 生效优先级（高 -> 低）

1. 进程环境变量（例如 compose `environment`）
2. `.env`
3. `.env.{CM_APP_ENV}`
4. `Settings` 默认值

### 3.3 当前关键配置项（必须掌握）

- `CM_APP_ENV`
- `CM_APP_HOST`
- `CM_APP_PORT`
- `CM_APP_LOG_LEVEL`
- `CM_POSTGRES_DSN`
- `CM_REDIS_URL`
- `CM_CLICKHOUSE_HTTP_URL`
- `CM_MINIO_ENDPOINT`

---

## 4. 组件深度说明

## 4.1 App（`cm-app`）

### 4.1.1 作用

- 提供统一 API 入口
- 暴露健康检查：`/healthz`
- 暴露 Prometheus 指标：`/metrics`

### 4.1.2 对应文件

- `src/app/main.py`
- `deploy/Dockerfile.app`
- `deploy/docker-compose.yml`（`app` service）

### 4.1.3 启动方式

- 本地虚拟环境：
  - `.\.venv\Scripts\python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --reload`
- 容器方式：
  - 由 compose 启动，命令已在 service 中定义

### 4.1.4 健康检查机制

- compose healthcheck 通过请求 `http://localhost:8000/healthz`
- 失败重试：`interval=10s`, `timeout=5s`, `retries=10`

### 4.1.5 常见问题

- 问题：`/healthz` 200 但业务接口报错
  - 说明：健康检查仅表示进程在，不代表业务依赖全可用
  - 处理：检查依赖服务连接、日志和配置项

---

## 4.2 PostgreSQL（`cm-postgres`）

### 4.2.1 作用

- 主事务数据库（配置、元数据、策略版本、迁移状态）
- Alembic 默认目标数据库

### 4.2.2 对应配置

- compose service：`postgres`
- 环境变量：
  - `POSTGRES_USER=cm`
  - `POSTGRES_PASSWORD=cm`
  - `POSTGRES_DB=chainmonitor`
- DSN（容器内互联）：
  - `postgresql+psycopg://cm:cm@postgres:5432/chainmonitor`

### 4.2.3 数据持久化

- 卷：`postgres_data:/var/lib/postgresql/data`

### 4.2.4 健康检查

- `pg_isready -U cm -d chainmonitor`

### 4.2.5 备份恢复

- 备份：`.\scripts\dev.ps1 -Command backup`
- 恢复：`.\scripts\dev.ps1 -Command restore -BackupFile <file>`
- 脚本支持自动识别 full/lite 容器名

### 4.2.6 常见问题

- 端口冲突（5432 已占用）
  - 处理：释放端口或修改映射

---

## 4.3 ClickHouse（`cm-clickhouse`）

### 4.3.1 作用

- 分析型数据存储预留（高频指标、报表、回测明细）
- 当前阶段主要是底座准备

### 4.3.2 对应配置

- HTTP 端口：`8123`
- Native 端口：`9000`
- 卷：`clickhouse_data:/var/lib/clickhouse`

### 4.3.3 健康检查

- `clickhouse-client --query 'SELECT 1'`

### 4.3.4 当前接入状态

- App 配置项已预留：`CM_CLICKHOUSE_HTTP_URL`
- 业务层尚未写入/查询逻辑（属后续业务阶段）

---

## 4.4 Redis（`cm-redis`）

### 4.4.1 作用

- 缓存与队列能力预留（实时分数、队列、临时状态）

### 4.4.2 对应配置

- 端口：`6379`
- 启动参数：`--appendonly yes`（AOF 持久化）
- 卷：`redis_data:/data`
- URL：`redis://redis:6379/0`

### 4.4.3 健康检查

- `redis-cli ping`

---

## 4.5 MinIO（`cm-minio`）

### 4.5.1 作用

- 对象存储能力预留（报告、归档、快照）

### 4.5.2 对应配置

- Console：`9001`
- S3 API 映射：`9002 -> container 9000`
- 默认账号：
  - `MINIO_ROOT_USER=minio`
  - `MINIO_ROOT_PASSWORD=minio123`

### 4.5.3 健康检查

- `curl -f http://localhost:9000/minio/health/live`

### 4.5.4 安全建议（后续）

- 不要在生产使用默认账号密码
- 开启访问策略与最小权限

---

## 4.6 Prometheus（`cm-prometheus`）

### 4.6.1 作用

- 拉取指标
- 执行告警规则

### 4.6.2 关键文件

- `infra/monitoring/prometheus/prometheus.yml`
- `infra/monitoring/prometheus/alerts.yml`

### 4.6.3 当前抓取目标

- `prometheus:9090`
- `app:8000/metrics`

### 4.6.4 当前告警规则

- `ChainMonitorAppDown`：App 持续不可抓取 2 分钟
- `HighAppRequestVolume`：5 分钟请求增量异常偏高

### 4.6.5 运维命令

- 健康：`http://localhost:9090/-/healthy`
- 重载（已启 `--web.enable-lifecycle`）：
  - `POST http://localhost:9090/-/reload`

---

## 4.7 Grafana（`cm-grafana`）

### 4.7.1 作用

- 指标看板可视化
- 快速观察服务状态

### 4.7.2 关键文件

- 数据源：`infra/monitoring/grafana/provisioning/datasources/datasource.yml`
- Dashboard Provider：`infra/monitoring/grafana/provisioning/dashboards/dashboard.yml`
- Dashboard JSON：`infra/monitoring/grafana/dashboards/chainmonitor-overview.json`

### 4.7.3 默认账号

- `admin/admin`

### 4.7.4 当前预置看板

- `ChainMonitor Overview`
  - 面板 1：`HTTP Requests / 5m`
  - 面板 2：`App Up`

---

## 5. 容器编排设计（full vs lite）

### 5.1 full 编排文件

- 文件：`deploy/docker-compose.yml`
- 特点：
  - 全组件
  - 依赖健康检查 gating
  - 含监控链路与 dashboard 挂载

### 5.2 lite 编排文件

- 文件：`deploy/docker-compose.lite.yml`
- 特点：
  - 最小运行集（app + postgres + redis）
  - 资源占用低
  - 适用于快速调试和低配机器

### 5.3 切换策略

- 正常开发：优先 full
- 仅验证 API/脚本：可用 lite

---

## 6. 统一脚本体系（`scripts/*.ps1`）

## 6.1 `dev.ps1`（总入口）

这是项目内最重要脚本，所有常用操作都建议走它。

命令语义：

- `all`：新环境首选，一键跑通
- `init/up/migrate/check/smoke`：日常最常用
- `backup/restore`：运维能力

## 6.2 `setup.ps1`

- 创建本地 `.venv`
- 校验 Python 版本（必须 3.11/3.12）
- 安装 `requirements/dev.txt`
- 若存在 `.git`，自动安装 pre-commit hook

## 6.3 `check.ps1`

执行顺序：

1. `ruff check`
2. `migration-check.ps1`
3. `pytest -q`
4. `pre_commit run --all-files`（若可用）

## 6.4 `smoke.ps1`

检查端点：

- `8000/healthz`
- `8000/metrics`
- `9090/-/healthy`
- `3000/api/health`

## 6.5 `db-backup.ps1` / `db-restore.ps1`

- backup：调用容器内 `pg_dump`
- restore：管道输入到容器内 `psql`
- 自动识别 full/lite 容器名

---

## 7. 数据库迁移体系（Alembic）

### 7.1 文件结构

- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/*.py`

### 7.2 迁移策略

- 多批次递进（核心表 -> 约束/批次2 -> 批次3）
- 每次变更必须保持：
  - 可升级
  - 可回滚（至少到 base）
  - CI 可重复执行

### 7.3 迁移最佳实践

- 一个迁移文件只做一类变更（结构/索引/约束）
- 名称可读（动词 + 对象）
- 增加约束时考虑历史数据兼容性

---

## 8. CI 深度说明

### 8.1 流程

CI 文件：`.github/workflows/ci.yml`

步骤：

1. 创建 `.venv` 并安装依赖
2. ruff
3. pytest
4. 启动 uvicorn 做 smoke（healthz + metrics）

### 8.2 为什么先迁移再测试

- 先验证“底座完整性”
- 避免测试通过但迁移不可发布

---

## 9. 观测与告警落地建议

### 9.1 当前状态

- 已有最小告警与看板
- 指标量级还不够全面（当前偏基础）

### 9.2 下一步建议（可选增强）

- 增加 DB/Redis/队列延迟指标
- 增加迁移执行耗时指标
- 增加 5xx 比例与 p95 延迟告警

---

## 10. 运行手册（Runbook）

### 10.1 新环境启动 Runbook

1. `.\scripts\dev.ps1 -Command all`
2. 若失败，按失败步骤单独重跑
3. 先修迁移问题，再修服务可达问题

### 10.2 日常开发 Runbook

1. `up`
2. `migrate`
3. `check`
4. 开发
5. 提交前 `check + smoke`

### 10.3 故障恢复 Runbook

1. `status` 查看容器状态
2. `logs` 看 app/prometheus/grafana
3. `smoke` 快速判断外部可用性
4. 需要回档时先 `backup`，再操作

---

## 11. 故障排查矩阵（按现象）

### 11.1 `all` 卡在 `setup`

- 检查 Python 版本
- 检查网络与 pip 源

### 11.2 `all` 卡在 `up`

- 端口冲突（8000/5432/6379/9090/3000）
- Docker Desktop 未运行

### 11.3 `all` 卡在 `migrate`

- PostgreSQL 未健康
- 迁移文件有语法/依赖问题

### 11.4 `all` 卡在 `check`

- ruff 规则违规
- pytest 失败
- pre-commit hook 扫描失败

### 11.5 `all` 卡在 `smoke`

- app 未就绪或崩溃
- prometheus/grafana 未启动

---

## 12. 安全与合规注意事项

- `.env` 不入库
- MinIO 默认账号仅用于本地开发
- 生产密码不能硬编码在 compose
- 备份文件属于敏感数据，需加访问控制

---

## 13. 容量与成本建议

- 本地资源紧张时优先 `up-lite`
- 仅在需要观测链路时启动 full
- 定期清理无用卷和镜像

---

## 14. 扩展指南（下一阶段）

当你要扩展基础设施时，建议按以下顺序：

1. 在 `config.py` 增加配置项
2. 在 `.env.*.example` 补对应变量
3. 在 compose 增加 service/挂载/健康检查
4. 在 `dev.ps1` 增加命令入口（如需要）
5. 在 `check`/CI 中加入最小验证
6. 回写 `INFRASTRUCTURE_GUIDE.md` 与本文件

---

## 15. 三层文档维护约定

- `README.md`：只放“快速上手 + 核心命令 + 入口链接”
- `INFRASTRUCTURE_GUIDE.md`：放“框架级解释与标准流程”
- `INFRASTRUCTURE_DEEP_DIVE.md`：放“组件级细节、运维与排障”

更新原则：

- 任何脚本/compose/监控配置变更，至少更新第 2 或第 3 层文档
- 若影响新同学上手路径，必须更新第 1 层 README

---

## 16. 最小可执行命令清单（复制即用）

```powershell
# 1) 首次一键
.\scripts\dev.ps1 -Command all

# 2) 日常开发
.\scripts\dev.ps1 -Command up
.\scripts\dev.ps1 -Command migrate
.\scripts\dev.ps1 -Command check

# 3) 提交前
.\scripts\dev.ps1 -Command smoke

# 4) 收工
.\scripts\dev.ps1 -Command down
```
