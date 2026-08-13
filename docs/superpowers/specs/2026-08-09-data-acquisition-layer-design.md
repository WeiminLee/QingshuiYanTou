# 数据获取层渐进式增强设计

**日期：** 2026-08-09

## 目标

在保留当前 `DataSourceClient`、`DataFetcher`、`KlineService`、PostgreSQL 表结构和既有 Agent/API 契约的前提下，补全 K 线及核心数据源获取能力，提升数据正确性、可用性和故障降级能力。

## 背景与约束

当前 K 线采集主要依赖 baostock，写入 `daily_data`；查询通过 `KlineService` 左连接 `daily_basic`。研报、公告、互动易已有双源或专用通道，新闻主要依赖 Tushare 代理。现有工作区包含未提交改动，本次只修改本设计涉及的文件，不覆盖或回退其他改动。

本次不整体移植参考项目的 `DataFetcherManager`，也不一次性引入所有海外数据源。先建立兼容现有链路的 provider 边界，并以 efinance/akshare 作为国内 K 线和实时行情的补充通道；可选源通过配置懒加载。

## 方案

### 1. K 线标准协议与故障切换

新增轻量 provider 协议，统一接受项目格式 `ts_code`、`start_date`、`end_date`，返回标准记录字段：`date`、`open`、`high`、`low`、`close`、`preclose`、`pctChg`、`volume`、`amount`、`tradestatus`。baostock 作为默认源；当其调用抛出异常或返回空结果时，按配置顺序尝试 efinance/akshare。provider 不改变现有入库模型，适配逻辑集中在数据获取层。

代码标准化沿用当前 `DataSourceClient` 的 `ts_code` 规则，所有 provider 在调用前转换到自身格式。故障切换记录 source、错误类型和最终结果，避免静默成功；单次同步不因一个 provider 失败而中断其他股票。

### 2. K 线数据正确性

- 原始 baostock 查询加入 `preclose` 字段，首条记录没有前一交易日时保留真实源值或为空，不再用当日收盘价伪造。
- 复权策略显式配置，默认保持当前不复权兼容行为；新增前复权路径时通过既有 `get_adjust_factor()` 计算 OHLC，禁止在没有复权因子时悄悄改变价格。
- K 线保存继续使用 `ON CONFLICT` 更新模式，确保 fallback 获取的数据能够修正同日旧记录。
- 同一批次的 `pct_chg` 优先采用源字段；缺失时由 `close` 与 `preclose` 计算，并保持百分比单位。

### 3. `daily_basic` 与查询频率

在 K 线写入流程中增加 `daily_basic` 可选写入，字段映射只写入实际可获得的数据，使用 `(ts_code, trade_date)` 幂等 upsert。数据源无基本面字段时仍成功保存 `daily_data`，不得因为基本面为空导致整只股票失败。

`KlineService.get_stock_kline()` 保持日线返回结构不变；当 `frequency` 为 `w` 或 `m` 时，先查询覆盖请求范围的日线，再在内存中按交易周或自然月聚合：open 取首条、high 取最大、low 取最小、close 取末条、volume/amount 求和、pct_chg 由聚合前收计算。非法频率回退为空结果或明确记录 warning，不改变现有调用方异常语义。

### 4. 调度、新闻及其他通道

- `_run_kline_job()` 使用 `backfill_config` 的 scope，不在调度器中硬编码 `tech_mvp`；保留白名单作为默认安全配置，并提供全市场周末回填入口。
- 新闻服务先使用现有 Tushare 代理，失败或空结果时调用已有 `DataSourceClient.get_cls_telegraph()`，统一映射到 `events` 并保留幂等事件 ID。
- 研报、公告、互动易、概念和市场宽度本轮不重写已有通道，只补充 provider 健康/失败日志和相关测试，避免扩大数据模型变更范围。

## 数据流

```text
调度器/手动任务
  -> DataFetcher.fetch_stock_kline
  -> provider registry: baostock -> efinance/akshare
  -> 标准记录适配与数据质量校验
  -> daily_data upsert
  -> daily_basic best-effort upsert
  -> KlineService 日线查询或周/月聚合
  -> API / Agent get_kline
```

```text
NewsService.fetch_and_save
  -> Tushare proxy
  -> 失败/空结果时 DataSourceClient.get_cls_telegraph
  -> 统一事件字段、稳定 event_id、幂等写入 events
```

## 错误处理与可观测性

- provider 异常、空响应、字段不完整分别记录 source、ts_code、时间范围和错误类型。
- fallback 只在本次调用内生效，不把空结果缓存为长期成功。
- `daily_data` 与 `daily_basic` 分开计数，结果返回 `kline_success`、`basic_success`、`fallback_used`、`fail` 等可诊断统计。
- 现有 readiness 查询继续以本地表最新日期为准；新增测试确保 `daily_basic` 缺失不会掩盖 K 线可用性。

## 测试策略

1. provider 适配：标准字段映射、代码格式、空响应和异常 fallback。
2. K 线正确性：`preclose`、复权因子、`pct_chg`、幂等 upsert。
3. 基本面：`daily_basic` 有数据时写入，无数据时 K 线仍成功。
4. 查询：日线兼容、周线/月线 OHLCV 聚合、非法频率行为。
5. 调度：scope 配置传递和全市场入口。
6. 新闻：Tushare 成功、失败、空结果时 CLS fallback 与重复事件去重。

## 非目标

- 不整体复制参考项目的大型管理器和全部海外 provider。
- 不修改已有研报、公告、互动易的业务语义或数据库模型。
- 不在没有明确数据源字段契约的情况下填充虚假的基本面值。
