# 慢即是快：段永平公开动态追踪

一个每日归档段永平公开动态的静态站点 MVP。它把信息区分为三类：

- **本人账号**：雪球账号“大道无形我有型”的公开发言，需要提供个人可用的登录 Cookie 后自动抓取。
- **监管披露**：SEC EDGAR 中 `H&H International Investment, LLC` 的 `13F-HR` 文件，属于可核验原始披露。
- **媒体报道**：Google News RSS 中关于段永平的报道线索，页面明确标记“需核验”；该 feed 适合个人、非商业阅读看板。

`13F` 是季度末持仓披露，有时间延迟；媒体标题也不能被直接视为投资事实。页面因此不会把所有新闻都冒充为本人交易动态。

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

默认 SEC 请求标识包含本项目公开仓库地址。如需改成你的联系信息，可以设置：

```bash
TRACKER_USER_AGENT='DadaoTracker/1.0 your-email@example.com' python3 collect.py
```

## 每日发布

[.github/workflows/daily-refresh.yml](./.github/workflows/daily-refresh.yml) 已配置为每天北京时间 `09:15` 自动执行：

1. 抓取公开数据并更新归档 JSON。
2. 将新增归档提交回仓库，以便持续保留历史。
3. 部署静态页面到 GitHub Pages。

推送仓库后，在 GitHub 仓库的 `Settings > Pages` 将来源设为 **GitHub Actions**。如需雪球动态，再添加名为 `XUEQIU_COOKIE` 的 Actions Secret。
如需用自己的联系标识请求 SEC，再添加 `TRACKER_USER_AGENT` Secret。

## 验证

```bash
python3 -m unittest discover -s tests -v
```
