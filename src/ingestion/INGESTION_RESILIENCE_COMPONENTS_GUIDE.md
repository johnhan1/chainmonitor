# Ingestion 韧性组件详解

本文档面向 `src/ingestion/resilience/` 下拆分后的韧性模块，详细说明采集层组件职责、执行时机、行为语义与观测指标。

## 1. 韧性体系总览

当前采集层韧性能力由四层组成：

1. 原语层（基础控制件）
- `AsyncTokenBucket`：控制请求速率，防止打爆上游与本地资源。
- `AsyncCircuitBreaker`：在连续失败后短路请求，避免故障放大。

2. 策略层（可复用策略）
- `RetryPolicy`：重试判定、错误归因、`Retry-After` 解析、退避时间计算。

3. 基础设施层（并发与缓存）
- `SingleFlightGroup`：同 URL 并发去重。
- `ResponseCacheStore`：进程内缓存 + Redis 二级缓存。
- `RateLimiterRegistry`：进程内共享 `provider+chain` 令牌桶。
- `CircuitBreakerRegistry`：进程内共享 `provider+chain+endpoint` 熔断器。
- `ProviderBackoffRegistry`：进程内共享 provider 级退避保护。

4. 执行与观测层
- `ResilientHttpClient`：统一请求编排器，串联所有韧性能力。
- 记录请求结果、延迟、重试、限流、熔断状态、缓存命中率与错误分类，支持线上定位与容量调优。

---

## 2. 原语层组件

## 2.1 `AsyncTokenBucket`（异步令牌桶限流器）

### 组件职责
- 以“令牌”作为可消费配额，限制单位时间内可发起的请求数。
- 在高并发场景下平滑流量，降低 429 与上游拒绝风险。

### 关键参数
- `rate_per_second`：每秒生成令牌数（最小保护值 `0.01`）。
- `capacity`：桶容量（最大可突发请求量，最小保护值 `1.0`）。

### 执行逻辑
1. 每次 `acquire()` 时计算距离上次补充时间 `elapsed`。
2. 根据 `elapsed * rate_per_second` 回填令牌，且不超过 `capacity`。
3. 若令牌 >= 1，消费 1 个并立即放行。
4. 若令牌不足，计算缺口等待时间后 `sleep`，循环直到拿到令牌。

### 解决的问题
- 避免瞬时并发导致接口雪崩。
- 将“请求失败后才发现限频”变为“发送前主动节流”。

---

## 2.2 `AsyncCircuitBreaker`（异步熔断器）

### 组件职责
- 当错误连续发生时，临时阻断请求，防止持续打到故障上游。
- 在恢复窗口后逐步探测上游是否恢复。

### 状态机
- `closed`：正常放行，请求全部可通过。
- `open`：熔断打开，请求直接拒绝。
- `half_open`：半开探测，仅允许少量请求试探恢复。

### 关键参数
- `failure_threshold`：触发熔断所需连续失败次数。
- `recovery_seconds`：`open` 后最短恢复等待时间。
- `half_open_max_calls`：半开状态最大探测请求数。

### 执行逻辑
1. `allow_request()`：
- `open` 且未到恢复时间：拒绝。
- `open` 且到恢复时间：转 `half_open`。
- `half_open` 超过探测次数：拒绝。
- 其余：允许。
2. `record_success()`：
- 清零失败计数；若在 `open/half_open`，回到 `closed`。
3. `record_failure()`：
- `half_open` 失败：立即回 `open` 并重置探测计数。
- `closed` 下累计失败，达到阈值则转 `open`。

### 解决的问题
- 上游持续异常时避免“无意义重试风暴”。
- 通过半开探测控制恢复过程，降低抖动风险。

---

## 2.3 `RetryPolicy`（重试策略组件）

### 组件职责
- 统一定义“什么错误可以重试”。
- 统一定义“失败原因如何分类”。
- 统一定义“等待多久后再重试”。

### 关键能力
- `is_retryable_exception(exc)`：判定是否重试。
- `error_reason(exc)`：错误类型归因（如 `timeout`、`upstream_5xx`）。
- `retry_after_seconds(response)`：解析 `Retry-After`（秒值或 RFC 日期）。
- `retry_sleep_seconds(...)`：指数退避 + jitter + 上限保护。

---

## 2.4 `SingleFlightGroup`（并发去重组件）

### 组件职责
- 对同 key（当前是 URL）并发请求做去重。
- leader 发请求，follower 等待同一个 `Future` 结果。

### 解决的问题
- 防止同一时刻重复请求击穿上游和缓存。

---

## 2.5 `ResponseCacheStore`（缓存组件）

### 组件职责
- 管理一级进程内缓存（LRU/TTL）。
- 管理二级 Redis 缓存（可选）。

### 关键行为
- 查询顺序：内存 -> Redis。
- 写入顺序：内存 -> Redis。
- key 规范：`sha256(provider:chain_id:url)` + namespace。

### 解决的问题
- 降低上游请求频率，提升吞吐与稳定性。

---

## 2.6 `ResilienceMetrics`（指标组件）

### 组件职责
- 封装请求、延迟、重试、限流、熔断、缓存命中等指标更新。
- 从请求编排中剥离指标细节，减少业务噪声。
- 指标统一携带 `provider` 维度，支持多源并行调优与归因。

---

## 3. 执行层组件：`ResilientHttpClient`

`ResilientHttpClient` 是采集层统一请求编排器，职责是按固定顺序调度各韧性组件，而不是在单文件内实现全部细节。

### Provider 维度限流
- `ResilientHttpClient` 初始化时必须传入 `provider`（如 `dexscreener`、`geckoterminal`、`birdeye`）。
- 令牌桶参数不再只看全局值，而是按 provider 解析，支持 provider+chain 精细覆盖。
- 这使三个数据源可以使用各自官方限流阈值，避免“低限额源被打爆”或“高限额源吃不满”。

## 3.1 请求生命周期（核心流程）

一次 `get_json(url, endpoint, trace_id, trace)` 的执行顺序：

1. 本地/Redis 缓存查询（命中直接返回）。
2. singleflight 去重（同 URL 并发请求只让一个“leader”请求上游，其他等待结果）。
3. 熔断检查（`allow_request()` 失败则直接短路并记指标）。
4. 令牌桶限流（`acquire()`）。
5. 发起 HTTP 请求（统一超时与连接池）。
6. 错误判定与重试（429/5xx/超时等进入退避重试）。
7. 成功后写缓存并返回 JSON。
8. 记录指标与日志，释放 singleflight 占位。

---

## 3.2 组件详解（按能力拆分）

### A. HTTP 超时与连接池
- 使用 `httpx.AsyncClient`。
- 全局超时：`market_data_timeout_seconds`（有最小保护）。
- 连接池限制：`max_connections`、`max_keepalive_connections`、`keepalive_expiry`。
- 作用：防止连接泄漏、僵尸连接和无限阻塞。

### B. 自动重试与失败分类
- 重试触发：
  - `httpx.TimeoutException`
  - `HTTPStatusError` 且状态码属于 `429/500/502/503/504`
  - 其他可归类 `httpx.HTTPError`
- 非可重试异常：快速失败（fail-fast），直接记录失败并返回 `None`。
- 错误分类标签：
  - `timeout`
  - `rate_limited`
  - `upstream_5xx`
  - `http_<code>`
  - `transport_error`
  - `parse_error`

### C. 退避策略（Backoff）
- 优先遵从上游 `Retry-After`（秒值或日期格式）。
- 否则采用：指数退避 + 随机抖动（jitter）。
- 上限由 `market_data_retry_max_sleep_seconds` 限制。
- 作用：减少同步重试导致的流量共振。

### D. 熔断整合
- 通过 `CircuitBreakerRegistry` 共享 `provider+chain+endpoint` 熔断状态。
- 熔断打开时直接返回 `None`，并记录阻塞时长与开关状态。
- 请求成功调用 `record_success()`，失败调用 `record_failure()`。

### D.1 Provider 级退避保护
- 通过 `ProviderBackoffRegistry` 共享 `provider+chain` 退避状态。
- 连续失败时对 provider 整体做短时退避，避免多 endpoint 同时压测上游。

### E. singleflight（同 URL 去重）
- 委托 `SingleFlightGroup` 维护 `url -> Future` 映射。
- leader 执行真实请求并写入 Future，follower 等待相同结果。
- 作用：避免同一时刻 N 个相同请求同时击穿上游与缓存。

### F. 两级缓存（进程内 + Redis）
- 委托 `ResponseCacheStore` 管理缓存查询、写入与容量收缩。
- 一级：进程内 `OrderedDict` + TTL。
- 二级：可选 Redis（跨实例共享缓存，支持 `setex`）。
- 作用：降低上游调用频率，提高稳定性与吞吐。

### G. 资源生命周期管理
- `aclose()` 统一关闭 HTTP client 与 Redis client。
- 提供 `async with` 上下文协议，便于策略层安全使用。

---

## 4. 可观测性指标说明

以下指标由 `ResilientHttpClient` 暴露：

- `cm_ingestion_requests_total{chain_id, endpoint, status}`
- `cm_ingestion_requests_total{chain_id, provider, endpoint, status}`
  - 请求总数，含 `success/error/cache_hit/blocked/singleflight_wait` 等状态。
- `cm_ingestion_request_latency_seconds{chain_id, endpoint}`
- `cm_ingestion_request_latency_seconds{chain_id, provider, endpoint}`
  - 上游请求延迟分布（Histogram）。
- `cm_ingestion_retries_total{chain_id, endpoint}`
- `cm_ingestion_retries_total{chain_id, provider, endpoint}`
  - 重试次数。
- `cm_ingestion_rate_limited_total{chain_id, endpoint}`
- `cm_ingestion_rate_limited_total{chain_id, provider, endpoint}`
  - 命中 429 的次数。
- `cm_ingestion_errors_total{chain_id, reason}`
- `cm_ingestion_errors_total{chain_id, provider, reason}`
  - 按错误原因聚合的失败次数。
- `cm_ingestion_circuit_open_seconds_total{chain_id, endpoint}`
- `cm_ingestion_circuit_open_seconds_total{chain_id, provider, endpoint}`
  - 熔断打开累计阻塞时长。
- `cm_ingestion_circuit_open{chain_id, endpoint}`
- `cm_ingestion_circuit_open{chain_id, provider, endpoint}`
  - 熔断是否打开（Gauge，1 为打开）。
- `cm_ingestion_cache_lookups_total{chain_id, result}`
- `cm_ingestion_cache_lookups_total{chain_id, provider, result}`
  - 缓存查询次数（`hit/miss`）。
- `cm_ingestion_cache_hit_ratio{chain_id}`
- `cm_ingestion_cache_hit_ratio{chain_id, provider}`
  - 缓存命中率。

---

## 5. 组件关系与边界

- `rate_limiter.py`、`circuit_breaker.py` 提供可复用控制原语。
- `retry_policy.py`、`singleflight.py`、`cache_store.py`、`metrics.py` 提供独立能力组件。
- `resilient_http_client.py` 仅做请求编排与生命周期管理。
- 数据源 adapter/strategy 只应该调用 `ResilientHttpClient.get_json()`，不要重复实现重试、熔断、缓存逻辑。

---

## 6. 常见调优建议

1. 429 频繁：
- 降低 `rate_per_second` 或 `max_concurrency`，适当增加缓存 TTL。

2. 熔断频繁打开：
- 检查上游稳定性与超时阈值；提高 `failure_threshold` 或延长 `recovery_seconds`。

3. 请求延迟高：
- 调整连接池参数，确认 DNS/网络链路，必要时降低单批请求体积。

4. 缓存命中率低：
- 检查 URL 是否稳定（query 参数是否导致 key 震荡），适当增加 TTL。

5. 重试无效且成本高：
- 收紧可重试条件，缩短最大重试次数，避免在硬错误上过度重试。

---

## 7. 限流配置优先级（按数据源拆分）

限流配置解析优先级如下（从高到低）：

1. `provider + chain` 覆盖
- `CM_MARKET_DATA_RATE_LIMIT_PER_SECOND_BY_PROVIDER_CHAIN`
- `CM_MARKET_DATA_RATE_LIMIT_CAPACITY_BY_PROVIDER_CHAIN`
- 格式：`provider:chain=value`，例如 `dexscreener:bsc=3.5`

2. `provider` 覆盖
- `CM_MARKET_DATA_RATE_LIMIT_PER_SECOND_BY_PROVIDER`
- `CM_MARKET_DATA_RATE_LIMIT_CAPACITY_BY_PROVIDER`
- 格式：`provider=value`，例如 `geckoterminal=2`

3. `chain` 覆盖
- `CM_MARKET_DATA_RATE_LIMIT_PER_SECOND_BY_CHAIN`
- `CM_MARKET_DATA_RATE_LIMIT_CAPACITY_BY_CHAIN`
- 格式：`chain=value`，例如 `bsc=9`

4. 全局默认
- `CM_MARKET_DATA_RATE_LIMIT_PER_SECOND`
- `CM_MARKET_DATA_RATE_LIMIT_CAPACITY`

推荐起步值（可按官方公告和实测 429 逐步微调）：
- `dexscreener=4 rps, capacity=8`
- `geckoterminal=2 rps, capacity=4`
- `birdeye=8 rps, capacity=16`
