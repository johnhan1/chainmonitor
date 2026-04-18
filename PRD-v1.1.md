# V1.1 可执行 PRD

- 范围：在上一版 `v1.0` 基础上，补齐“可直接落地”的数据结构、因子字典、统一事件模型与执行口径。
- 目标：工程可按此拆任务，量化可按此定义实验，产品可按此验收闭环。

## 一、系统边界

- 输入：`SOL / BASE / BSC / ETH` 的链上交易、池子、持仓、合约标签、社媒热度。
- 处理：标准化、特征生成、评分、信号、回测、模拟实盘、归因、进化。
- 输出：`候选池(A/B/C)`、`交易信号`、`回测报告`、`模拟实盘日报`、`策略版本变更建议`。
- 原则：优先保证“净收益与风险收益比”，不以胜率为核心 KPI。

## 二、数据库表结构草案（字段级）

- `chains`
  - `chain_id`(PK), `chain_name`, `native_symbol`, `block_time_ms`, `is_evm`, `status`, `created_at`
- `tokens`
  - `token_id`(PK), `chain_id`, `address`, `symbol`, `name`, `decimals`, `first_seen_at`, `is_verified`, `status`
- `pairs_pools`
  - `pool_id`(PK), `chain_id`, `dex`, `pool_address`, `token0`, `token1`, `fee_tier`, `created_at`, `status`
- `market_ticks`（分钟级快照）
  - `id`(PK), `chain_id`, `token_id`, `ts_minute`, `price_usd`, `volume_1m`, `volume_5m`, `liquidity_usd`, `buys_1m`, `sells_1m`, `tx_count_1m`
- `onchain_flow_features`
  - `id`(PK), `chain_id`, `token_id`, `ts_minute`, `netflow_usd_5m`, `netflow_usd_30m`, `large_buy_count_30m`, `new_holder_30m`, `holder_churn_24h`
- `risk_features`
  - `id`(PK), `chain_id`, `token_id`, `ts_minute`, `contract_risk_score`, `lp_concentration`, `holder_concentration_top10`, `wash_trade_score`, `honeypot_flag`
- `smart_money_features`
  - `id`(PK), `chain_id`, `token_id`, `ts_minute`, `sm_buy_wallets_30m`, `sm_netflow_usd_30m`, `sm_winrate_weighted_score`
- `narrative_features`
  - `id`(PK), `chain_id`, `token_id`, `ts_minute`, `mention_count_30m`, `mention_growth_2h`, `dev_activity_score`, `cross_chain_narrative_score`
- `token_scores`
  - `id`(PK), `strategy_version`, `chain_id`, `token_id`, `ts_minute`, `alpha_score`, `momentum_score`, `smart_money_score`, `narrative_score`, `risk_penalty`, `final_score`, `conviction`, `confidence`
- `candidate_pool_snapshots`
  - `id`(PK), `ts_minute`, `strategy_version`, `chain_id`, `token_id`, `tier`(A/B/C), `rank`, `reason_codes(jsonb)`
- `trade_signals`
  - `signal_id`(PK), `strategy_version`, `chain_id`, `token_id`, `signal_time`, `side`, `entry_rule_id`, `exit_rule_id`, `signal_score`, `status`
- `paper_orders`
  - `order_id`(PK), `signal_id`, `placed_at`, `expected_px`, `filled_px`, `qty`, `notional_usd`, `slippage_bps`, `gas_usd`, `fee_usd`, `fill_status`
- `paper_positions`
  - `position_id`(PK), `chain_id`, `token_id`, `opened_at`, `closed_at`, `entry_px`, `exit_px`, `qty`, `pnl_usd`, `max_drawdown_pct`, `close_reason`
- `backtest_runs`
  - `run_id`(PK), `strategy_version`, `period_start`, `period_end`, `config_json`, `status`, `created_at`, `finished_at`
- `backtest_metrics`
  - `id`(PK), `run_id`, `net_pnl_usd`, `pf`, `win_rate`, `expectancy`, `max_dd_pct`, `sharpe_like`, `calmar_like`, `turnover`, `capacity_score`
- `strategy_versions`
  - `version_id`(PK), `parent_version`, `weights_json`, `thresholds_json`, `risk_rules_json`, `regime_rules_json`, `status`, `promoted_at`
- `data_source_health`
  - `id`(PK), `source_name`, `chain_id`, `ts_minute`, `latency_ms`, `success_rate`, `missing_rate`, `fallback_level`

## 三、关键索引与分区建议

- 高频表按 `ts_minute` 做时间分区：`market_ticks`, `*_features`, `token_scores`。
- 复合索引：`(chain_id, token_id, ts_minute desc)`。
- 候选池查询索引：`(ts_minute desc, tier, final_score desc)`。
- 回测明细索引：`(run_id, chain_id, token_id)`。

## 四、因子字典（v1）

- `F001_liquidity_depth`
  - 公式：`log(1 + liquidity_usd)`；频率：`1m`；方向：越大越好；权重初始：`0.10`
- `F002_volume_accel`
  - 公式：`volume_5m / max(volume_30m_avg, eps)`；频率：`1m`；方向：越大越好；权重：`0.08`
- `F003_buy_pressure`
  - 公式：`buys_5m / max(sells_5m,1)`；频率：`1m`；方向：越大越好；权重：`0.07`
- `F004_netflow_strength`
  - 公式：`zscore(netflow_usd_30m)`；频率：`1m`；方向：越大越好；权重：`0.10`
- `F005_holder_growth`
  - 公式：`new_holder_30m / max(holder_base,1)`；频率：`5m`；方向：越大越好；权重：`0.06`
- `F006_holder_concentration_penalty`
  - 公式：`top10_share`；频率：`5m`；方向：越小越好；惩罚权重：`0.08`
- `F007_lp_concentration_penalty`
  - 公式：`lp_top_provider_share`；频率：`5m`；方向：越小越好；惩罚权重：`0.05`
- `F008_contract_risk_penalty`
  - 公式：风险规则映射分（mint/blacklist/tax/upgradeability）；频率：`事件触发+10m复核`；惩罚权重：`0.12`
- `F009_smart_money_inflow`
  - 公式：`sm_netflow_usd_30m * sm_wallet_quality`；频率：`1m`；方向：越大越好；权重：`0.12`
- `F010_sm_participation`
  - 公式：`sm_buy_wallets_30m` 分位数；频率：`1m`；方向：越大越好；权重：`0.06`
- `F011_momentum_breakout`
  - 公式：`(px_now - rolling_high_60m)/rolling_high_60m`；频率：`1m`；方向：适中偏正；权重：`0.08`
- `F012_volatility_regime`
  - 公式：`atr_30m / px_now`；频率：`1m`；用途：阈值动态调节；不直接加分
- `F013_narrative_velocity`
  - 公式：`mention_growth_2h`；频率：`5m`；方向：越大越好（封顶）；权重：`0.04`
- `F014_wash_trade_penalty`
  - 公式：刷量检测模型分；频率：`1m`；惩罚权重：`0.07`
- `F015_data_confidence`
  - 公式：`完整率*新鲜度*跨源一致性`；频率：`1m`；用途：乘子 `confidence`

## 五、评分与门控规则（可执行）

- `Gate-1 可交易性`：`liquidity_usd >= L_min` 且 `volume_24h >= V_min`。
- `Gate-2 安全性`：`honeypot_flag=0` 且 `contract_risk_score <= R_max`。
- `Gate-3 操纵过滤`：`wash_trade_score <= W_max`。
- `Score`：
  - `AlphaScore = Σ(wi * norm(Fi_positive))`
  - `RiskPenalty = Σ(wj * norm(Fj_penalty))`
  - `FinalScore = 0.55*Alpha + 0.20*Momentum + 0.15*SmartMoney + 0.10*Narrative - RiskPenalty`
  - `Conviction = FinalScore * F015_data_confidence * RegimeFit`
- `分层`：`A: Conviction>=85`，`B:70-85`，`C:55-70`（可链别差异化）。
- `信号触发`：进入 A 且连续 `N` 个窗口保持；退出条件为止损/失效/时间到期。

## 六、统一事件模型（回测与模拟实盘共用）

- 事件类型：`MarketTick`, `FeatureReady`, `ScoreUpdated`, `SignalCreated`, `OrderPlaced`, `OrderFilled`, `PositionClosed`, `RiskAlert`。
- 事件统一字段：
  - `event_id`, `event_type`, `event_time`, `chain_id`, `token_id`, `strategy_version`, `payload_json`
- 关键约束：
  - 回测与模拟实盘使用同一撮合与成本函数。
  - 所有决策仅可读取 `event_time` 之前数据，杜绝未来函数。
  - 每次策略变更必须生成新 `strategy_version`。

## 七、回测口径规范

- 频率：`1m` 主回测，`5m` 稳健性复核。
- 样本切分：训练期 / 验证期 / 前向测试期（walk-forward）。
- 成本模型：链别 gas 中位数 + 深度冲击滑点 + DEX fee。
- 入场规则：`Conviction` 过阈值且 `confidence` 达标。
- 出场规则：固定止损、分层止盈、时间止盈、风险告警强平。
- 指标门槛（上线前）：
  - `PF >= 1.3`
  - `Expectancy > 0`
  - `MaxDD <= 预设阈值`
  - `容量冲击` 在可接受区间。

## 八、模拟实盘规范

- 撮合：按实时流动性曲线估算成交，不允许中间价理想成交。
- 延迟：注入 `signal->order`、`order->fill` 链路延迟分布。
- 风控：单币最大仓位、链别最大敞口、同叙事集中度上限。
- 日报：输出 `PnL、回撤、偏差（回测vs实盘）` 与失败样本标签。

## 九、自进化机制（每周）

- 输入：最近 `N` 天模拟实盘 + 回测前向窗口。
- 动作：权重微调、阈值微调、失效因子降权、链别参数分化。
- 约束：新版本若“收益提升但回撤恶化超阈值”则拒绝发布。
- 发布：`10%` 灰度 `->` `50%` `->` 全量，任一阶段触发风控即回滚。

## 十、接口契约（最小集）

- `POST /score/run`：触发实时评分批次。
- `GET /candidates?chain=...&tier=A`：读取候选池。
- `POST /backtest/run`：提交回测任务。
- `GET /backtest/{run_id}/metrics`：查询回测指标。
- `POST /paper/order/simulate`：注入模拟实盘订单。
- `GET /strategy/versions`：查看策略版本与变更。

## 十一、验收标准（DoD）

- 工程 DoD：核心链路可 7x24 运行，数据源故障自动切换成功。
- 量化 DoD：回测与模拟口径一致，关键指标可复现。
- 产品 DoD：信号可解释、可追溯、可归因，支持版本对比。
- 业务 DoD：滚动窗口总体净收益为正，风险指标不越界。

## 十二、实施优先级（两周冲刺建议）

- Sprint 1：数据接入、标准化、`market_ticks`+`features`+`token_scores` 三张核心表。
- Sprint 2：Gate+Score 引擎、A/B/C 候选池、基础告警。
- Sprint 3：回测引擎 MVP（统一事件模型）。
- Sprint 4：模拟实盘 MVP + 周期性进化任务。
