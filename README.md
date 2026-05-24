# 慢即是快：段永平公开动态追踪

一个归档段永平公开动态的静态站点 MVP。数据在本地抓取、摘要并提交后，由 GitHub Pages 发布。它把信息区分为三类：

- **本人账号**：雪球账号“大道无形我有型”的公开发言，需要提供个人可用的登录 Cookie 后自动抓取。
- **监管披露**：SEC EDGAR 中 `H&H International Investment, LLC` 的 `13F-HR` 文件，属于可核验原始披露。
- **媒体报道**：Google News RSS 中关于段永平的报道线索，页面明确标记“需核验”；该 feed 适合个人、非商业阅读看板。

`13F` 是季度末持仓披露，有时间延迟；媒体标题也不能被直接视为投资事实。页面因此不会把所有新闻都冒充为本人交易动态。

页面默认每页展示 10 条动态，支持类别筛选、关键词搜索和分页浏览。

## 查看本地站点

只需 Python 3.11+，无需安装依赖：

```bash
python3 -m http.server 8000
```

浏览器访问 `http://localhost:8000`。页面读取仓库中的 [data/feed.json](./data/feed.json)，浏览网页本身不会实时抓取外部数据。

## 开启雪球本人动态

雪球主页可公开访问，但动态接口通常需要登录态。在本地 `.env.local` 中设置 `XUEQIU_COOKIE`：

```bash
XUEQIU_COOKIE='your-cookie-value' python3 collect.py
```

Cookie 只作为请求环境变量使用，不应写入仓库。Cookie 失效时，页面的来源状态会显示读取异常，SEC 与媒体采集仍能继续。

SEC 要求请求标识包含可联系信息，因此采集该来源前需要设置：

```bash
TRACKER_USER_AGENT='DadaoTracker/1.0 your-email@example.com' python3 collect.py
```

## 开启自动摘要

监管披露和本人发言使用来源中可以直接核验的摘录。对于媒体报道，可配置 OpenAI API Key，在每日采集时逐批生成简短摘要：

```bash
OPENAI_API_KEY='your-api-key' python3 collect.py
```

脚本默认使用 `gpt-5.4-nano`，每次最多总结 10 条尚未处理的媒体记录。若能取得页面描述，页面标注“AI 摘要 · 页面描述”；若新闻聚合链接不暴露正文，模型会尝试联网检索对应报道并显示可点击引用，标注“AI 摘要 · 联网核验”；无法找到材料时才标注“AI 摘要 · 仅标题”。所有摘要都属于报道线索，仍应打开原文核验。

可调整的环境变量：

- `OPENAI_SUMMARY_MODEL`：摘要模型，默认 `gpt-5.4-nano`。
- `AI_SUMMARY_LIMIT`：每次最多生成的摘要数量，默认 `10`。

## 本地更新与发布

复制 [.env.local.example](./.env.local.example) 为 `.env.local`，填入本地专用配置：

```bash
cp .env.local.example .env.local
```

至少需要：

- `TRACKER_USER_AGENT`：SEC 请求需要的可联系标识。
- `OPENAI_API_KEY`：媒体报道在发布前生成 AI 摘要所需的密钥。

然后运行：

```bash
bash scripts/update_local.sh
```

该脚本严格按以下顺序执行：

1. 在本机抓取最新公开数据。
2. 对尚未处理的媒体条目生成 AI 摘要；默认一次补齐最多 500 条。
3. 执行测试。
4. 仅将生成后的 `data/feed.json` 提交并推送。
5. GitHub Pages 在收到推送后部署静态内容。

没有 `OPENAI_API_KEY` 时脚本会停止，不会把新增的待摘要媒体条目发布出去。

## GitHub Pages

[.github/workflows/daily-refresh.yml](./.github/workflows/daily-refresh.yml) 现在只负责在 `main` 分支被推送后部署静态站点，不在 GitHub Runner 上抓取或总结内容。这样公开页面展示的始终是你本地处理并确认提交的数据。

如需每天自动更新，可在保持本机在线的前提下，用本地定时任务每天调用 `bash scripts/update_local.sh`。

## 验证

```bash
python3 -m unittest discover -s tests -v
```
