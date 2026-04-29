# Shared Resilience Layer

`src/shared/resilience/` 提供一组传输无关的通用韧性（resilience）原语，以及一个编排器 `ResilientExecutor` 将它们组合成可复用的执行管道。

## 架构

```
ResilientExecutor.execute(fn)
│
├─ ① BackoffGuard.allow_request()    ← 全局退避：连续失败后快速跳过
├─ ② AsyncCircuitBreaker.allow_request()  ← 熔断：达到阈值后快速失败
│
├─ ③ Retry loop (1..retry_attempts)
│   ├─ AsyncTokenBucket.acquire()    ← 限流：令牌桶
│   ├─ fn()                          ← 实际调用（传输层）
│   ├─ on success → record_success() → return result
│   └─ on exception
│       ├─ retryable? → sleep + jitter → retry
│       └─ not retryable? → raise (传播给调用者)
│
└─ ④ Exhausted → record_failure() → return None
```

## 组件

### AsyncCircuitBreaker

状态机：`closed → open → half-open → closed`

| 状态 | 行为 |
|------|------|
| closed | 正常放行；连续失败达到 `failure_threshold` 后切换到 open |
| open | 拒绝所有请求；等待 `recovery_seconds` 后切换到 half-open |
| half-open | 允许最多 `half_open_max_calls` 个探测请求；成功则切回 closed，失败则回到 open |

```
from src.shared.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerRegistry

breaker = CircuitBreakerRegistry.get_breaker(
    name="my_service",
    failure_threshold=5,
    recovery_seconds=30.0,
    half_open_max_calls=2,
)
if await breaker.allow_request():
    try:
        result = await do_call()
        await breaker.record_success()
    except Exception:
        await breaker.record_failure()
```

### AsyncTokenBucket

令牌桶限流器，线程安全，支持突发（burst）。

```
from src.shared.resilience.rate_limiter import AsyncTokenBucket, RateLimiterRegistry

bucket = RateLimiterRegistry.get_bucket(
    name="my_service",
    rate_per_second=10.0,
    capacity=20,
)
await bucket.acquire()  # 可能阻塞直到有可用令牌
```

### BackoffGuard

连续失败后的指数退避守卫，与熔断器构成双层防护：

- 熔断器：基于失败计数（threshold 机制）
- BackoffGuard：基于连续失败次数（指数退避，无 threshold，任何失败都触发）

```
from src.shared.resilience.backoff import BackoffGuard, BackoffRegistry

guard = BackoffRegistry.get_guard(name="my_service")

now = monotonic()
if guard.allow_request(now):
    try:
        result = await do_call()
        guard.record_success()
    except Exception:
        guard.record_failure(
            now=now,
            base_seconds=1.0,
            max_seconds=30.0,
        )
```

退避策略：`cooldown = min(max_seconds, base * multiplier)`，其中 `multiplier = min(8, max(1, failure_streak))`。

### retry_sleep_seconds

指数退避 + 随机抖动（jitter）：

```python
sleep = min(max_seconds, base_seconds * (2 ** (attempt - 1)) + random(0, base_seconds))
```

```
from src.shared.resilience.retry import retry_sleep_seconds, RetryableCheck

sleep = retry_sleep_seconds(attempt=2, base_seconds=1.0, max_seconds=30.0)
await asyncio.sleep(sleep)
```

`RetryableCheck` 是一个 type alias：`Callable[[Exception], bool]`。

## ResilientExecutor — 编排器

将所有原语组合成单一调用接口。

### 定义

```python
from src.shared.resilience.executor import ResilienceConfig, ResilientExecutor

config = ResilienceConfig(
    rate_limit_per_second=2.0,
    rate_limit_capacity=5,
    circuit_failure_threshold=5,
    circuit_recovery_seconds=30.0,
    circuit_half_open_max_calls=2,
    retry_attempts=3,
    retry_base_seconds=1.0,
    retry_max_seconds=30.0,
    backoff_base_seconds=1.0,
    backoff_max_seconds=30.0,
)

executor = ResilientExecutor(
    name="my_service",
    config=config,
    is_retryable=lambda e: isinstance(e, (TimeoutError, OSError)),
)
```

### 调用

```python
result = await executor.execute(lambda: my_io_call(...))
```

| 场景 | 返回值 |
|------|--------|
| 成功 | `fn()` 的返回值 |
| 重试耗尽 | `None` |
| 熔断器打开 | `None` |
| Backoff 中 | `None` |
| 非可重试异常 | 向上传播（raise） |

### 可重试策略

`is_retryable` 是调用者提供的判定函数，决定哪些异常值得重试：

```python
# HTTP 调用
is_retryable = lambda e: isinstance(e, (httpx.TimeoutException, httpx.HTTPStatusError))

# 子进程调用
is_retryable = lambda e: isinstance(e, (TimeoutError, OSError))

# 自定义
def is_retryable(e: Exception) -> bool:
    if isinstance(e, TimeoutError):
        return True
    if isinstance(e, MyApiError) and e.code in {429, 502, 503}:
        return True
    return False
```

## 使用示例

### Scanner（子进程调用）

```python
from src.shared.resilience.executor import ResilienceConfig, ResilientExecutor

executor = ResilientExecutor(
    name="gmgn_trending",
    config=ResilienceConfig(
        rate_limit_per_second=2.0,
        retry_attempts=3,
    ),
    is_retryable=lambda e: isinstance(e, (TimeoutError, OSError)),
)
result = await executor.execute(lambda: run_subprocess(...))
```

### Ingestion（HTTP 调用）

Ingestion 通过 `src/ingestion/resilience/` 的兼容包装层间接使用，包装层将 `(provider, chain, endpoint)` 拼接成 name 后委托给 shared 组件：

```python
# 调用者无感知，import 路径不变
from src.ingestion.resilience.resilient_http_client import ResilientHttpClient
```

## 配置参考

| ResilienceConfig 字段 | 默认值 | 说明 |
|---|---|---|
| `rate_limit_per_second` | 2.0 | 令牌补充速率 |
| `rate_limit_capacity` | 5 | 令牌桶容量（突发大小） |
| `circuit_failure_threshold` | 5 | 熔断器打开前的连续失败次数 |
| `circuit_recovery_seconds` | 30.0 | 熔断器从 open 到 half-open 的等待时间 |
| `circuit_half_open_max_calls` | 2 | half-open 状态允许的探测请求数 |
| `retry_attempts` | 3 | 总尝试次数（含首次） |
| `retry_base_seconds` | 1.0 | 指数退避基数 |
| `retry_max_seconds` | 30.0 | 退避上限 |
| `backoff_base_seconds` | 1.0 | BackoffGuard 基数 |
| `backoff_max_seconds` | 30.0 | BackoffGuard 上限 |

## 注册中心

所有组件都有对应的注册中心（Registry），以 name 为键实现单例。相同 name 的组件共享同一个底层实例，天然实现全局限流和熔断状态共享。

| 注册中心 | 管理对象 | 键类型 |
|---|---|---|
| `CircuitBreakerRegistry` | `AsyncCircuitBreaker` | `str`（name，大小写不敏感） |
| `RateLimiterRegistry` | `AsyncTokenBucket` | `str`（name，大小写不敏感） |
| `BackoffRegistry` | `BackoffGuard` | `str`（name，大小写不敏感） |

## 新增传输方式

添加新的传输方式（如 websocket、gRPC）只需两步：

```python
# 1. 定义可重试判定
def is_retryable(e: Exception) -> bool: ...

# 2. 创建执行器并调用
executor = ResilientExecutor(name="my_service", config=config, is_retryable=is_retryable)
result = await executor.execute(lambda: my_io_call(...))
```

不需要重复实现熔断器、限流器、退避守卫、重试循环。
