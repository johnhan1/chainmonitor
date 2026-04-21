# Tasks
- [x] Task 1: 建立新分层骨架与契约
  - [x] SubTask 1.1: 新增 `provider_adapter.py` 定义统一 adapter 接口
  - [x] SubTask 1.2: 新增 `normalized_pair.py` 定义跨数据源统一中间模型
  - [x] SubTask 1.3: 新增 `pair_quality_policy.py` 提炼质量门禁规则
  - [x] SubTask 1.4: 新增 `base_live_source_strategy.py` 实现统一模板流程

- [x] Task 2: 抽离并落地统一韧性请求执行层
  - [x] SubTask 2.1: 新增 `resilient_http_client.py`，复用 `AsyncTokenBucket` 与 `AsyncCircuitBreaker`
  - [x] SubTask 2.2: 迁移重试、超时、退避、缓存、singleflight 与请求指标逻辑
  - [x] SubTask 2.3: 删除旧策略中已迁移且重复的请求私有方法

- [x] Task 3: 重构 DexScreener 为薄策略 + adapter
  - [x] SubTask 3.1: 新增 `dexscreener_adapter.py`，仅负责 endpoint 调用与字段映射
  - [x] SubTask 3.2: 改造 `dexscreener_source_strategy.py` 为装配层
  - [x] SubTask 3.3: 保持对外行为一致（输出结构、错误语义、关键指标）

- [x] Task 4: 接入第二实时数据源（无兼容层）
  - [x] SubTask 4.1: 新增 `geckoterminal_provider_adapter.py` 与 `geckoterminal_source_strategy.py`
  - [x] SubTask 4.2: 扩展 `source_strategy_factory.py` 注册表与校验逻辑
  - [x] SubTask 4.3: 在 `__init__.py` 导出新增策略并完成模块整合

- [x] Task 5: 配置、测试与文档同步
  - [x] SubTask 5.1: 在 `Settings` 增加第二源必要配置项（`CM_` 前缀）
  - [x] SubTask 5.2: 新增/更新测试（成功路径、失败路径、fallback 补齐路径）
  - [x] SubTask 5.3: 更新 `INGESTION_ARCHITECTURE_GUIDE.md` 与相关说明文档
  - [x] SubTask 5.4: 运行静态检查与测试并修复问题

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 1 and Task 2
- Task 5 depends on Task 3 and Task 4
