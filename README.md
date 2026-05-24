# 慢即是快：段永平公开动态追踪

一个每日归档段永平公开动态的静态站点 MVP。它把信息区分为三类：

- **本人账号**：雪球账号“大道无形我有型”的公开发言，需要提供个人可用的登录 Cookie 后自动抓取。
- **监管披露**：SEC EDGAR 中 `H&H International Investment, LLC` 的 `13F-HR` 文件，属于可核验原始披露。
- **媒体报道**：Google News RSS 中关于段永平的报道线索，页面明确标记“需核验”；该 feed 适合个人、非商业阅读看板。

`13F` 是季度末持仓披露，有时间延迟；媒体标题也不能被直接视为投资事实。页面因此不会把所有新闻都冒充为本人交易动态。

页面默认每页展示 10 条动态，支持类别筛选、关键词搜索和分页浏览。

## 本地运行

只需 Python 3.11+，无需安装依赖：

```bash
python3 collect.py
python3 -m http.server 8000
```

浏览器访问 `http://localhost:8000`。每次运行 `collect.py` 会读取最新来源，并与 [data/feed.json](./data/feed.json) 中的旧数据去重合并，最多保留 500 条。

## 开启雪球本人动态

雪球主页可公开访问，但动态接口通常需要登录态。在本地或 GitHub Actions 的 Secret 中设置 `XUEQIU_COOKIE`：

```bash
XUEQIU_COOKIE='your-cookie-value' python3 collect.py
```

Cookie 只作为请求环境变量使用，不应写入仓库。Cookie 失效时，页面的来源状态会显示读取异常，SEC 与媒体采集仍能继续。

SEC 要求请求标识包含可联系信息，因此采集该来源前需要设置：

```bash
TRACKER_USER_AGENT='DadaoTracker/1.0 your-email@example.com' python3 collect.py
```

## 开启自动摘要

监管披露和本人发言使用来源中可以直接核验的摘录。对于媒体报道，可配置 OpenAI 官方 API Key，或兼容 Responses API 的第三方中转接口，在每日采集时逐批生成简短摘要。

使用 OpenAI 官方接口：

```bash
OPENAI_API_KEY='your-api-key' python3 collect.py
```

使用兼容 Responses API 的第三方中转站：

```bash
SUMMARY_API_KEY='your-provider-key' \
SUMMARY_API_BASE_URL='https://your-provider.example/v1' \
SUMMARY_API_STYLE='responses' \
SUMMARY_MODEL='your-model-id' \
SUMMARY_SUPPORTS_WEB_SEARCH='false' \
python3 collect.py
```

若中转站仅兼容 Chat Completions：

```bash
SUMMARY_API_KEY='your-provider-key' \
SUMMARY_API_BASE_URL='https://your-provider.example/v1' \
SUMMARY_API_STYLE='chat_completions' \
SUMMARY_MODEL='your-model-id' \
SUMMARY_SUPPORTS_WEB_SEARCH='false' \
python3 collect.py
```

脚本默认使用 `gpt-5.4-nano`，每次最多总结 10 条尚未处理的媒体记录。若能取得页面描述，页面标注“AI 摘要 · 页面描述”；若接口支持 Responses `web_search` 且新闻链接不暴露正文，模型会尝试联网检索对应报道并显示可点击引用，标注“AI 摘要 · 联网核验”；无法找到材料时才标注“AI 摘要 · 仅标题”。所有摘要都属于报道线索，仍应打开原文核验。

可调整的环境变量：

- `SUMMARY_API_KEY`：第三方兼容接口 Key；未设置时回退到 `OPENAI_API_KEY`。
- `SUMMARY_API_BASE_URL`：兼容接口根路径，默认 `https://api.openai.com/v1`。
- `SUMMARY_API_STYLE`：`responses`（默认）或 `chat_completions`；后者不启用联网搜索引用。
- `SUMMARY_MODEL`：摘要模型；未设置时回退到 `OPENAI_SUMMARY_MODEL`，再回退到 `gpt-5.4-nano`。
- `SUMMARY_SUPPORTS_WEB_SEARCH`：接口是否支持 Responses 的 `web_search` 工具，默认 `true`；不确定时对中转站设为 `false`。
- `AI_SUMMARY_LIMIT`：每次最多生成的摘要数量，默认 `10`。

## 每日发布

[.github/workflows/daily-refresh.yml](./.github/workflows/daily-refresh.yml) 已配置为每天北京时间 `09:15` 自动执行：

1. 抓取公开数据并更新归档 JSON。
2. 将新增归档提交回仓库，以便持续保留历史。
3. 部署静态页面到 GitHub Pages。

推送仓库后，在 GitHub 仓库的 `Settings > Pages` 将来源设为 **GitHub Actions**。如需雪球动态，再添加名为 `XUEQIU_COOKIE` 的 Actions Secret；如需媒体自动摘要，可添加 `OPENAI_API_KEY` Secret，或添加 `SUMMARY_API_KEY` Secret 并在 Actions Variables 中设置 `SUMMARY_API_BASE_URL`、`SUMMARY_API_STYLE`、`SUMMARY_MODEL`、`SUMMARY_SUPPORTS_WEB_SEARCH`。
部署时需要添加 `TRACKER_USER_AGENT` Secret 才能每日检查 SEC；未设置时，页面会保留既有归档并将该来源显示为待配置。

## 验证

```bash
python3 -m unittest discover -s tests -v
```
