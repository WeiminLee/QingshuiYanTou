# 数据接入服务 API 文档

> 本服务提供中国A股市场数据接入能力，支持研报、公告、互动易、财联社电报、K线等数据的查询、拉取与管理。
>
- **Base URL**: `http://124.221.188.38:8080/api/v1`
- **认证**: 无
- **响应格式**: JSON

---

## 目录

- [认证与通用说明](#1-认证与通用说明)
- [健康检查](#2-健康检查)
- [研报与公告查询](#3-研报与公告查询)
- [互动易查询](#4-互动易查询)
- [财联社电报](#5-财联社电报)
- [个股K线](#6-个股k线)
- [指数K线](#7-指数k线)
- [股票列表](#8-股票列表)
- [股票概况（主营业务）](#9-股票概况主营业务)
- [数据拉取触发](#10-数据拉取触发)
- [任务日志](#11-任务日志)
- [附录：数据统计与字段说明](#附录数据统计与字段说明)

---

## 1. 认证与通用说明

### 通用请求头

本服务目前无鉴层，所有接口公开访问。生产环境部署时请自行在反向代理层（如 Nginx）配置认证。

```
Content-Type: application/json
```

### 通用响应格式

所有接口均返回 JSON，错误时 HTTP 状态码非 200，响应体含 `detail` 字段说明原因。

### 通用查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从1开始 |
| `page_size` | int | 50 | 每页条数，最大200 |

---

## 2. 健康检查

### `GET /health`

服务健康检查接口，用于探活。

**请求**

```
GET /health
```

**响应**

```json
{
  "status": "ok",
  "service": "data_access_mvp"
}
```

---

## 3. 研报与公告查询

### 3.1 分页查询 `/api/v1/query`

查询研报或公告数据列表，支持多维筛选。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data_type` | string | 否 | 数据类型：`report`（研报）或 `notice`（公告） |
| `ts_code` | string | 否 | 股票代码，如 `000001.SZ` |
| `doc_type` | string | 否 | 公告分类标签（仅 notice 有效），见 [附录：doc_type 说明](#doc_type-公告分类标签) |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认50，最大200 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的总条数 |
| `page` | int | 当前页码 |
| `page_size` | int | 每页条数 |
| `items` | array | 数据项数组 |

**`items` 字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ann_id` | string | 唯一标识，可用于下载 |
| `data_type` | string | `report` 或 `notice` |
| `ts_code` | string | 股票代码 |
| `title` | string | 标题 |
| `pub_date` | string | 发布日期，YYYYMMDD |
| `doc_type` | string | 公告分类标签 |
| `file_size` | int | 文件大小（字节），0表示无文件 |
| `file_url` | string/null | 文件下载地址（存在时提供） |
| `fetch_time` | string | 入库时间，ISO 格式 |

**请求示例**

```
GET /api/v1/query?data_type=report&start_date=20260401&page=1&page_size=20
```

**响应示例**

```json
{
  "total": 8316,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "ann_id": "report_xxx.pdf",
      "data_type": "report",
      "ts_code": "000001.SZ",
      "title": "平安银行深度报告",
      "pub_date": "20260418",
      "doc_type": "report",
      "file_size": 524288,
      "file_url": "/api/v1/download/report_xxx.pdf",
      "fetch_time": "2026-04-18T16:30:00"
    }
  ]
}
```

---

### 3.2 游标增量拉取 `/api/v1/fetch`

增量拉取数据，按入库时间顺序返回。适用于将数据同步到外部系统。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `cursor` | string | 否 | 游标，不传表示从头开始 |
| `limit` | int | 否 | 本次拉取条数，默认500，最大1000 |
| `data_type` | string | 否 | `report` 或 `notice` |
| `ts_code` | string | 否 | 股票代码筛选 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `next_cursor` | string/null | 下次调用传入的游标，`null` 表示已拉完 |
| `has_more` | bool | 是否还有更多数据 |
| `items` | array | 数据项数组，结构同 `/query` |

**请求示例**

```
GET /api/v1/fetch?limit=500&data_type=report
GET /api/v1/fetch?cursor=<next_cursor>&limit=500
```

---

### 3.3 轻量 ann_id 列表 `/api/v1/ann_ids`

分页列出所有 ann_id，轻量接口，适合批量获取标识后再逐条查详情。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data_type` | string | 否 | `report` 或 `notice` |
| `ts_code` | string | 否 | 股票代码 |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认100，最大1000 |

---

### 3.4 查询单条详情 `/api/v1/data/{ann_id}`

根据 ann_id 查询数据元信息。

**请求示例**

```
GET /api/v1/data/report_xxx.pdf
```

---

### 3.5 下载文件 `/api/v1/download/{ann_id}`

下载研报或公告 PDF 文件。

**请求示例**

```
GET /api/v1/download/report_xxx.pdf
```

**响应**：文件流，`Content-Type: application/pdf`，文件名含原文件后缀。

> 注意：公告中不需要下载的类型（如日常公告）无文件，`file_size` 为 0。

---

## 4. 互动易查询

> 互动易（深交所 `SZ` + 上交所 `SH`）Q&A 数据，截至文档生成日共 **14,425** 条记录。
>
> 深交所（0/3 开头股票）：全量入库，不过滤。
> 上交所（6 开头股票）：按信号词过滤后入库。

### 4.1 分页查询 `/api/v1/irm`

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 否 | 股票代码，如 `000001.SZ` |
| `exchange` | string | 否 | 交易所：`SZ` 或 `SH` |
| `keyword` | string | 否 | 关键词搜索（问题内容） |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认50，最大200 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的总条数 |
| `page` | int | 当前页码 |
| `page_size` | int | 每页条数 |
| `items` | array | 互动易问答项 |

**`items` 字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ann_id` | string | 唯一标识 |
| `ts_code` | string | 股票代码 |
| `exchange` | string | `SZ` 或 `SH` |
| `question` | string | 投资者提问 |
| `answer` | string | 公司回复 |
| `question_time` | string | 提问时间，YYYY-MM-DD HH:MM:SS |
| `answer_time` | string | 回复时间，YYYY-MM-DD HH:MM:SS |
| `signals` | string | 逗号分隔的信号词（上交所过滤词命中后填充） |
| `stock_name` | string | 公司简称 |
| `pub_date` | string | 提问日期，YYYYMMDD |

**请求示例**

```
GET /api/v1/irm?ts_code=000001.SZ&page=1&page_size=20
GET /api/v1/irm?exchange=SZ&start_date=20260401&page_size=50
```

---

### 4.2 游标增量拉取 `/api/v1/irm/fetch`

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `cursor` | string | 否 | 游标，不传从头开始 |
| `limit` | int | 否 | 本次拉取条数，默认500，最大1000 |
| `ts_code` | string | 否 | 股票代码筛选 |
| `exchange` | string | 否 | 交易所：`SZ` 或 `SH` |

---

## 5. 财联社电报

### 5.1 查询乐晴文章 `/api/v1/leqing/articles`

查询乐晴智库文章列表。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 关键词搜索（标题） |
| `source` | string | 否 | 来源名称 |
| `tag` | string | 否 | 标签名称，如 `信息科技`、`大消费` |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认50，最大200 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的总条数 |
| `items[].ann_id` | string | 唯一标识 |
| `items[].title` | string | 文章标题 |
| `items[].source` | string | 来源 |
| `items[].source_url` | string | 原文链接 |
| `items[].wx_img` | string | 封面图 URL |
| `items[].tags` | string | 标签，逗号分隔 |
| `items[].pub_date` | string | 发布日期，YYYYMMDD |
| `items[].fetch_time` | string | 入库时间，ISO 格式 |

---

## 6. 个股K线

> 个股日K线数据，存储 **5,130** 只股票，共 **2,440,770** 条记录。
> 数据范围：2015-01-05 ～ 2026-04-22（前复权数据）。
> 数据来源：baostock（免费，无需 token）。

### 6.1 分页查询 `/api/v1/kline/stock`

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 否 | 股票代码，如 `000001.SZ` |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `frequency` | string | 否 | 频率：`d` 日K（默认）/ `w` 周K / `m` 月K |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认100，最大500 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的总条数 |
| `items[].ts_code` | string | 股票代码 |
| `items[].trade_date` | string | 交易日期，YYYYMMDD |
| `items[].frequency` | string | 频率 |
| `items[].open` | string | 开盘价（原始） |
| `items[].high` | string | 最高价（原始） |
| `items[].low` | string | 最低价（原始） |
| `items[].close` | string | 收盘价（原始） |
| `items[].preclose` | string | 前收价 |
| `items[].volume` | string | 成交量（股） |
| `items[].amount` | string | 成交额（元） |
| `items[].pct_chg` | string | 涨跌幅（%） |
| `items[].turnover_rate` | string | 换手率（%） |
| `items[].qfq_factor` | string | **前复权因子** |

> **前复权价计算**：将原始价乘以 `qfq_factor` 即得前复权价。
> 例如：`前复权收盘价 = close × qfq_factor`

**请求示例**

```
GET /api/v1/kline/stock?ts_code=000001.SZ&start_date=20260101&page_size=100
```

---

### 6.2 最新一根K线 `/api/v1/kline/stock/latest`

快速获取某只股票的最新一根K线，用于图表初始化。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | **是** | 股票代码，如 `000001.SZ` |
| `frequency` | string | 否 | 频率：`d`（默认）/ `w` / `m` |

**响应**：单个 `StockKlineItem` 对象，无外层包装。

**请求示例**

```
GET /api/v1/kline/stock/latest?ts_code=000001.SZ
```

---

### 6.3 批量查询 `/api/v1/kline/stock/batch`

一次查询多只股票的K线，适合自选股初始化场景。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_codes` | string | **是** | 股票代码列表，逗号分隔，最多50个，如 `000001.SZ,600519.SH,000002.SZ` |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `frequency` | string | 否 | 频率：`d`（默认）/ `w` / `m` |
| `limit_per_stock` | int | 否 | 每只股票最多返回条数，默认100，最大500 |

**响应**

```json
{
  "codes": 3,
  "stocks": {
    "000001.SZ": [ /* StockKlineItem[] */ ],
    "600519.SH": [ /* StockKlineItem[] */ ],
    "000002.SZ": [ /* StockKlineItem[] */ ]
  }
}
```

**请求示例**

```
GET "/api/v1/kline/stock/batch?ts_codes=000001.SZ,600519.SH&limit_per_stock=100"
```

---

### 6.4 入库状态 `/api/v1/kline/stock/status`

查看个股K线入库统计。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 否 | 传入则返回该股票详情；不传则返回全局统计 |

**不传 `ts_code` 时响应**

```json
{
  "total_stocks": 5130,
  "total_rows": 2440770,
  "stocks": [
    {
      "ts_code": "000001.SZ",
      "start_date": "20150105",
      "end_date": "20260422",
      "count": 2420
    }
  ]
}
```

**传 `ts_code` 时响应**

```json
{
  "ts_code": "000001.SZ",
  "start_date": "20150105",
  "end_date": "20260422",
  "count": 2420
}
```

---

### 6.5 手动触发入库 `POST /api/v1/kline/stock/trigger`

从 baostock 拉取个股K线数据入库，增量模式（已入库股票自动跳过）。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_codes` | string | 否 | 逗号分隔的股票代码；不传则回补全市场 A 股 |
| `years` | int | 否 | 回补年数，默认1，最大10 |

> 注意：全市场回补约 5,000 只股票，耗时较长（预计数小时），建议通过 CLI 方式运行：
> ```bash
> python main.py backfill --task stock_kline --years 1
> ```

**响应示例**

```json
{
  "success": true,
  "message": "个股K线入库完成",
  "result": {
    "total_stocks": 5130,
    "success": 2440770,
    "skipped": 0,
    "no_data": 0,
    "elapsed_seconds": 3600.5
  }
}
```

---

## 7. 指数K线

> 监控 6 只主要指数的日K线数据，截至文档生成日共 **216** 条记录。
> 数据范围：2026-03-02 ～ 2026-04-21。

| baostock 代码 | 指数名称 |
|--------------|---------|
| `sh.000001` | 上证指数 |
| `sh.000016` | 上证50 |
| `sh.000300` | 沪深300 |
| `sz.399001` | 深证成指 |
| `sz.399005` | 中小板指 |
| `sz.399006` | 创业板指 |

### 7.1 分页查询 `/api/v1/kline`

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `index_code` | string | 否 | 指数代码，如 `sh.000001` |
| `start_date` | string | 否 | 开始日期，YYYYMMDD |
| `end_date` | string | 否 | 结束日期，YYYYMMDD |
| `frequency` | string | 否 | 频率：`d` 日K（默认）/ `w` 周K / `m` 月K |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认100，最大500 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 总条数 |
| `items[].index_code` | string | 指数代码 |
| `items[].trade_date` | string | 交易日期，YYYYMMDD |
| `items[].frequency` | string | 频率 |
| `items[].open/high/low/close/preclose` | string | OHLC 价格 |
| `items[].volume` | string | 成交量（股） |
| `items[].amount` | string | 成交额（元） |
| `items[].pct_chg` | string | 涨跌幅（%） |

---

### 7.2 最新K线 `/api/v1/kline/latest`

获取各指数最新交易日数据。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `index_code` | string | 否 | 不传则返回所有监控指数最新一条；传入则只返回该指数 |

**不传 `index_code` 响应**

```json
{
  "indices": 6,
  "items": [ /* KlineItem[] */ ]
}
```

---

### 7.3 入库状态 `/api/v1/kline/status`

```json
{
  "status": "ok",
  "indices": [
    {
      "index_code": "sh.000001",
      "start_date": "20260302",
      "end_date": "20260421",
      "count": 36
    }
  ]
}
```

---

## 8. 股票列表

### `GET /api/v1/stocks`

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `has_data` | bool | 否 | `false`（默认）：返回所有股票列表；`true`：只返回有数据的股票并附带数据条数 |

**`has_data=false` 响应**

```json
{
  "stocks": [
    { "ts_code": "000001.SZ", "name": "平安银行" },
    { "ts_code": "600519.SH", "name": "贵州茅台" }
  ]
}
```

**`has_data=true` 响应**

```json
{
  "stocks": [
    { "ts_code": "000001.SZ", "count": 1520 },
    { "ts_code": "600519.SH", "count": 842 }
  ]
}
```

---

## 9. 股票概况（主营业务）

> 股票主营业务概况数据，数据来源为同花顺 `stock_zyjs_ths` 接口。
> 支持按月定期覆盖更新（建议每月1日凌晨执行一次）。

### 9.1 查询单条 `/api/v1/stock/profile`

根据股票代码查询主营业务概况。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | **是** | 股票代码，如 `000001.SZ` |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | string | 股票代码 |
| `main_business` | string | 主营业务一句话概述 |
| `product_type` | string | 产品类型（逗号分隔的结构化分类） |
| `product_name` | string | 具体产品名称 |
| `business_scope` | string | 工商登记的经营范围全文 |
| `updated_at` | string | 最后更新时间，ISO 格式 |

**请求示例**

```
GET /api/v1/stock/profile?ts_code=600519.SH
```

**响应示例**

```json
{
  "ts_code": "600519",
  "main_business": "茅台酒及系列酒的生产与销售。",
  "product_type": "茅台酒、其他系列酒",
  "product_name": "茅台酒、其他系列酒",
  "business_scope": "茅台酒及系列酒的生产与销售；饮料、食品、包装材料的生产、销售；...",
  "updated_at": "2026-04-22T21:30:04"
}
```

---

### 9.2 分页列表 `/api/v1/stock/profile/list`

分页列出股票概况，支持关键词搜索。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 关键词，模糊匹配主营业务或产品名称 |
| `page` | int | 否 | 页码，默认1 |
| `page_size` | int | 否 | 每页条数，默认50，最大200 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的总条数 |
| `items` | array | `StockProfileItem` 数组 |

---

### 9.3 入库统计 `/api/v1/stock/profile/status`

查看股票概况入库情况。

```json
{
  "total": 4,
  "oldest_update": "2026-04-22T21:30:04",
  "newest_update": "2026-04-22T21:30:05"
}
```

---

### 9.4 手动触发回补 `POST /api/v1/stock/profile/trigger`

从同花顺拉取股票概况，覆盖更新。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_codes` | string | 否 | 逗号分隔的股票代码；不传则回补全市场 A 股 |

> 全市场约 5,000 只股票，耗时约 40 分钟，建议通过 CLI 方式运行：
> ```bash
> python main.py backfill --task stock_profile
> ```

**响应示例**

```json
{
  "success": true,
  "message": "股票概况回补完成",
  "result": {
    "total_stocks": 5130,
    "success": 5100,
    "skipped": 0,
    "no_data": 30,
    "elapsed_seconds": 2400.5
  }
}
```

---

## 10. 数据拉取触发

### 10.1 通用数据触发 `POST /api/v1/trigger`

手动触发一次数据拉取（通过 akshare / baostock / 巨潮接口）。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data_type` | string | **是** | 数据类型：`report` / `notice` / `irm` / `cls` / `all` |

**响应示例**

```json
{
  "success": true,
  "message": "数据拉取完成",
  "result": {
    "report": { "total": 50, "success": 48, "fail": 0, "skip": 2 },
    "notice": { "total": 200, "indexed": 180, "downloaded": 30, "skipped": 20 }
  }
}
```

---

### 10.2 乐晴数据触发 `POST /api/v1/leqing/trigger`

手动触发乐晴智库数据拉取。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `fetch_type` | string | **是** | `news`（资讯）/ `reports`（研报）/ `all` |
| `keyword` | string | 否 | 关键词搜索 |
| `category` | string | 否 | 研报分类，如 `大消费`、`信息科技`（仅 reports 生效） |
| `max_items` | int | 否 | 最多拉取条数（仅 news 生效），默认200，最大1000 |
| `max_pages` | int | 否 | 最多翻页数（仅 reports 生效），默认50，最大200 |

---

## 11. 任务日志

### `GET /api/v1/logs`

查询数据拉取任务的执行历史。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_type` | string | 否 | 任务类型：`report` / `notice` 等 |
| `limit` | int | 否 | 返回条数，默认50，最大200 |

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 日志 ID |
| `task_type` | string | 任务类型 |
| `start_time` | string | 开始时间，ISO 格式 |
| `end_time` | string/null | 结束时间 |
| `duration` | int/null | 耗时（秒） |
| `status` | string | `running` / `success` / `failed` / `partial` |
| `total_count` | int | 总条数 |
| `success_count` | int | 成功数 |
| `fail_count` | int | 失败数 |
| `skip_count` | int | 跳过数 |
| `error_msg` | string/null | 错误信息 |

---

## 附录：数据统计与字段说明

### 当前数据规模

| 数据类型 | 总条数 | 数据范围 | 更新频率 |
|---------|--------|---------|---------|
| 研报 (report) | 8,316 | — | 每日 |
| 公告 (notice) | 71,448 | — | 每日 |
| 互动易 (irm) | 14,425 | — | 每日 |
| 财联社电报 (cls) | 20 | — | 每分钟 |
| 个股日K线 | 2,440,770 | 2015-01-05 ～ 2026-04-22 | 每日收盘后 |
| 指数日K线 | 216 | 2026-03-02 ～ 2026-04-21 | 每日收盘后 |
| 股票概况 (stock_profile) | 4 | — | 每月一次（建议每月1日） |

### 个股K线频率说明

| frequency | 说明 |
|-----------|------|
| `d` | 日K线（默认） |
| `w` | 周K线 |
| `m` | 月K线 |

### doc_type 公告分类标签

公告数据（`data_type=notice`）根据标题关键词自动分类，常见类型：

| doc_type | 说明 |
|---------|------|
| `annual` | 年度报告 |
| `q1` | 一季度报 |
| `mid` | 中期报告 |
| `q3` | 三季度报 |
| `audit` | 审计报告 |
| ` Prospectus` | 招股说明书 |
| `equity` | 股权变动 |
| `shareholder` | 股东增减持 |
| `corporate` | 重要事项 |
| `bankruptcy` | 破产重整 |
| `split` | 股份分拆 |
| `ipo` | 上市相关 |

> **文件下载说明**：年报、半年报、季报、审计报告、招股说明书等**重要报告**会自动下载 PDF 文件；日常公告仅建索引，不下载文件。研报（report）根据机构策略决定是否下载。

### 前复权因子说明

个股K线中 `qfq_factor` 字段用于消除因分红送股产生的价格断层。

```
前复权价 = 原始价 × qfq_factor
```

服务端可直接用原始价格乘以前复权因子，前端无需自行计算。

### 服务启动方式

```bash
# 初始化数据库
python main.py init

# 仅运行定时任务（不启动 API）
python main.py scheduler

# 仅启动 API 服务
python main.py api

# 同时运行定时任务 + API
python main.py all

# 立即执行定时任务（不常驻）
python main.py scheduler --now

# 手动单次拉取
python main.py once --task report      # 研报
python main.py once --task notice      # 公告
python main.py once --task irm         # 互动易
python main.py once --task cls         # 财联社

# 手动单次拉取指数K线
python main.py once --task kline

# 批量回补（历史数据）
python main.py backfill --task report --days 365          # 研报回补 365 天
python main.py backfill --task notice --days 365         # 公告回补 365 天
python main.py backfill --task stock_kline --years 1    # 个股K线回补 1 年
python main.py backfill --task stock_profile            # 股票概况全量回补
```

### 定时任务调度时间

| 任务 | 调度时间 | 说明 |
|------|---------|------|
| 研报 | 每日 16:30 | 收盘后获取当天研报 |
| 公告 | 每日 17:00 | 收盘后获取当天公告 |
| 互动易 | 每日 22:00 | 盘后获取 |
| 指数K线 | 每日 17:30 | 收盘后入库 |
| 财联社电报 | 每分钟 | 实时接入 |
| 数据清理 | 每周一 03:00 | 清理过期数据 |
| 股票同步 | 每周一 07:00 | 同步全市场股票列表 |
| 股票概况 | 每月1日 04:00 | 覆盖更新全市场主营业务数据 |
