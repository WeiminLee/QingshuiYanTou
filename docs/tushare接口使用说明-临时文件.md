Ts 数据接口使用指南
1. 获取 API Key
打开卖家发给你的兑换页面：


当前可用的apikey: 086520ee148add8a401f8a5f04644ef2d04abbff5494461a  ----有效期到明天


https://teajoin.com/redeem
Copy
输入兑换码，即可获得你的专属 API Key 和到期时间。兑换码可重复使用，随时回来输入同一兑换码即可重新查看 Key。

返回示例：

{"api_key": "c14680ec99fb6de2d8509ef72f938453", "expires_at": "2026-06-08 17:47:34"}
Copy
请妥善保存 API Key。如忘记，重新输入兑换码即可找回。

2. 安装依赖
pip install tushare pandas
Copy
3. 调用方式
方式一：使用 Ts SDK（推荐，最简单）
如果你已经在用 tushare Python 包，只需改两行代码。如果你之前设置过 token 环境变量，记得要删除。

import tushare as ts

# 把 token 设为兑换获得的 API Key
ts.set_token("*** 替换为你获取的 API Key ***")

# 修改 API 地址指向本服务
pro = ts.pro_api()
pro._DataApi__http_url = "https://teajoin.com"

# 然后正常使用
df = pro.daily(ts_code='000001.SZ', start_date='20260101', end_date='20260110')
print(df)
Copy
特殊情形 1：ts.pro_bar() 等模块级函数，必须手动传 api=pro

import tushare as ts

ts.set_token("*** 替换为你的 API Key ***")
pro = ts.pro_api()
pro._DataApi__http_url = "https://teajoin.com"

df = ts.pro_bar(ts_code='002594.SZ', api=pro, start_date='20180101', end_date='20181011', adj='qfq')
print(df)
Copy
方式二：直接 HTTP 请求
如果不方便用 ts SDK，可以直接 POST 到根路径 /：

import requests

resp = requests.post("https://teajoin.com", json={
    "api_name": "daily",
    "token": "*** 替换为你获取的 API Key ***",
    "params": {
        "ts_code": "000001.SZ",
        "start_date": "20260101",
        "end_date": "20260110"
    }
})

data = resp.json()
print(data)
Copy
方式三：MCP 协议（接入 AI 大模型）
将 ts 数据接入 Claude、Cursor、Codex 等支持 MCP 的 AI 工具，让大模型直接调用数据。

在你的 AI 工具 MCP 配置文件中添加：

{
  "mcpServers": {
    "tushare": {
      "url": "https://teajoin.com/mcp/?api_key=你的API_KEY"
    }
  }
}
Copy
配好后在 AI 对话里说"查一下000001.SZ最近一周的日线行情"，AI 自动调接口返回数据。

4. 常用接口速查
接口名	用途	常用参数
daily	日线行情	ts_code, trade_date, start_date, end_date
weekly	周线行情	ts_code, start_date, end_date
monthly	月线行情	ts_code, start_date, end_date
daily_basic	每日指标	ts_code, trade_date
stock_basic	股票列表	exchange, list_status
trade_cal	交易日历	exchange, start_date, end_date
income	利润表	ts_code, start_date, end_date
balancesheet	资产负债表	ts_code, start_date, end_date
cashflow	现金流量表	ts_code, start_date, end_date
index_daily	指数日线	ts_code, start_date, end_date
limit_list	涨跌停列表	trade_date, ts_code
moneyflow	个股资金流向	ts_code, trade_date
stk_limit	涨跌停价格	ts_code, trade_date
5. 常见问题
Q: 数据格式和官方 ts 一样吗？ A: 完全一致。代理服务直接透传 ts 原始响应，字段名、数据类型均不变。

Q: 支持哪些接口？ A: 支持 Ts Pro 所有对应积分权限的数据接口。

Q: 和直接用 Ts 有什么区别？ A: 返回数据格式完全一致。你只需把 _DataApi__http_url 指向本服务地址，Token 设为你的 API Key 即可，代码几乎不用改。

Q: 到期怎么办？ A: 访问 /redeem 输入兑换码即可查看到期时间。如已到期，联系卖家购买新兑换码续费。

Q: 怎么知道自己的到期时间？ A: 访问 /redeem 输入兑换码即可查看。

Q: 阶段性程序超时/报错？ A: 大概率是请求速度远超合理值触发了冷却。请检查代码中的请求间隔，冷却期过后自动恢复。

Q: 我的 Key 过期了怎么办？ A: 重新找卖家购买即可获得新的 Key。如需延长原 Key，请联系卖家后台操作。
