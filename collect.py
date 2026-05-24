#!/usr/bin/env python3
"""Collect public updates about Duan Yongping into a static JSON feed."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "feed.json"
SEC_CIK = "0001759760"
XUEQIU_USER_ID = "1247347556"
XUEQIU_PROFILE = f"https://xueqiu.com/u/{XUEQIU_USER_ID}"
SUMMARY_MODEL = (
    os.environ.get("SUMMARY_MODEL", "").strip()
    or os.environ.get("OPENAI_SUMMARY_MODEL", "").strip()
    or "gpt-5.4-nano"
)
SUMMARY_LIMIT = int(os.environ.get("AI_SUMMARY_LIMIT", "10"))
SUMMARY_API_BASE_URL = (
    os.environ.get("SUMMARY_API_BASE_URL", "").strip().rstrip("/")
    or "https://api.openai.com/v1"
)
SUMMARY_API_STYLE = os.environ.get("SUMMARY_API_STYLE", "").strip().lower() or "responses"
SUMMARY_SUPPORTS_WEB_SEARCH = (os.environ.get("SUMMARY_SUPPORTS_WEB_SEARCH", "").strip() or "true").lower() in {
    "1", "true", "yes", "on"
}
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip()
ANTHROPIC_AUTH_STYLE = os.environ.get("ANTHROPIC_AUTH_STYLE", "").strip().lower() or "x-api-key"
USER_AGENT = (
    os.environ.get("TRACKER_USER_AGENT", "").strip()
    or "DadaoTracker/1.0 https://github.com/fashen007/dadaozhijian"
)


@dataclass
class FeedItem:
    id: str
    category: str
    title: str
    summary: str
    source: str
    source_type: str
    published_at: str
    url: str
    collected_at: str
    verification: str
    summary_status: str
    summary_basis: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_date(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: str) -> str:
    return prefix + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:18]


def text_only(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def secure_context() -> ssl.SSLContext:
    system_certs = Path("/etc/ssl/cert.pem")
    if not os.environ.get("SSL_CERT_FILE") and system_certs.exists():
        return ssl.create_default_context(cafile=str(system_certs))
    return ssl.create_default_context()


def request_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25, context=secure_context()) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("请求重试意外结束")


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=request_headers, method="POST")
    with urlopen(request, timeout=45, context=secure_context()) as response:
        return json.loads(response.read())


def meta_description(html_data: bytes) -> str:
    page = html_data.decode("utf-8", errors="ignore")
    patterns = (
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:description|og:description)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.I)
        if match:
            value = text_only(match.group(1))
            boilerplate = ("Google 新闻", "Google News", "aggregated from sources all over the world")
            if len(value) >= 20 and not any(marker in value for marker in boilerplate):
                return value[:1200]
    return ""


def classify_news(title: str) -> str:
    if re.search(
        r"持仓|持有|持股|买入|买股|加仓|增持|减持|减仓|清仓|建仓|重仓|调仓|换仓|换了|"
        r"押注|下注|被套|投资|基金|13F|股票|股价|看跌期权|卖出|重估|出手",
        title,
        re.I,
    ):
        return "investment"
    if re.search(r"采访|专访|对话|演讲|谈|称|表示|回应|回复|表态|发声|三问|否认|评|不同意", title, re.I):
        return "interview"
    return "personal"


def parse_google_news(xml_data: bytes, collected_at: str) -> list[FeedItem]:
    root = ElementTree.fromstring(xml_data)
    results: list[FeedItem] = []
    for entry in root.findall("./channel/item"):
        source = entry.findtext("source", default="媒体报道").strip()
        raw_title = entry.findtext("title", default="").strip()
        title = raw_title.removesuffix(f" - {source}").strip()
        url = entry.findtext("link", default="").strip()
        pub_date = entry.findtext("pubDate", default="")
        if not title or not url or not pub_date:
            continue
        results.append(
            FeedItem(
                id=stable_id("news", url),
                category=classify_news(title),
                title=title,
                summary="媒体检索结果，请打开原报道核验上下文与原始引述。",
                source=source,
                source_type="媒体报道",
                published_at=iso_date(parsedate_to_datetime(pub_date)),
                url=url,
                collected_at=collected_at,
                verification="需核验",
                summary_status="pending",
                summary_basis="等待 AI 摘要",
            )
        )
    return results


def fetch_google_news(fetch: Callable[..., bytes], collected_at: str) -> tuple[list[FeedItem], dict[str, str]]:
    query = quote('"段永平" OR "大道无形我有型"')
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        items = parse_google_news(fetch(url), collected_at)
        return items, source_state("news", "媒体报道", "ok", f"获取 {len(items)} 条 Google News RSS 结果", collected_at)
    except Exception as exc:
        return [], source_state("news", "媒体报道", "error", f"读取失败：{exc}", collected_at)


def parse_sec(payload: dict[str, Any], collected_at: str) -> list[FeedItem]:
    recent = payload["filings"]["recent"]
    results: list[FeedItem] = []
    for index, form in enumerate(recent["form"]):
        if not form.startswith("13F-HR"):
            continue
        accession = recent["accessionNumber"][index]
        filing_date = recent["filingDate"][index]
        report_date = recent["reportDate"][index]
        document = recent["primaryDocument"][index]
        accession_path = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(SEC_CIK)}/{accession_path}/{document}"
        results.append(
            FeedItem(
                id=f"sec-{accession}",
                category="investment",
                title=f"H&H International Investment 提交 {form} 持仓披露",
                summary=f"报告期截至 {report_date}；13F 为季度末披露，不代表实时交易。",
                source="SEC EDGAR",
                source_type="监管披露",
                published_at=f"{filing_date}T00:00:00Z",
                url=url,
                collected_at=collected_at,
                verification="原始披露",
                summary_status="source",
                summary_basis="监管披露说明",
            )
        )
    return results


def fetch_sec(fetch: Callable[..., bytes], collected_at: str) -> tuple[list[FeedItem], dict[str, str]]:
    contact_user_agent = os.environ.get("TRACKER_USER_AGENT", "").strip()
    if not contact_user_agent:
        return [], source_state(
            "sec",
            "SEC 13F",
            "setup",
            "设置 TRACKER_USER_AGENT 后每日检查 SEC 13F；既有披露归档仍会保留",
            collected_at,
        )
    url = f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json"
    try:
        payload = json.loads(
            fetch(url, {"Accept": "application/json", "User-Agent": contact_user_agent})
        )
        items = parse_sec(payload, collected_at)
        return items, source_state("sec", "SEC 13F", "ok", f"获取 {len(items)} 份持仓披露", collected_at)
    except Exception as exc:
        return [], source_state("sec", "SEC 13F", "error", f"读取失败：{exc}", collected_at)


def parse_xueqiu(payload: dict[str, Any], collected_at: str) -> list[FeedItem]:
    rows = payload.get("list") or payload.get("statuses") or []
    results: list[FeedItem] = []
    for row in rows:
        raw = text_only(row.get("description") or row.get("text") or "")
        item_id = str(row.get("id") or row.get("status_id") or "")
        if not raw or not item_id:
            continue
        created = row.get("created_at")
        if isinstance(created, (int, float)):
            published_at = iso_date(datetime.fromtimestamp(created / 1000, timezone.utc))
        else:
            published_at = collected_at
        category = "investment" if classify_news(raw) == "investment" else "statement"
        results.append(
            FeedItem(
                id=f"xueqiu-{item_id}",
                category=category,
                title=raw[:72] + ("..." if len(raw) > 72 else ""),
                summary=raw[:260] + ("..." if len(raw) > 260 else ""),
                source="大道无形我有型 / 雪球",
                source_type="本人账号",
                published_at=published_at,
                url=f"https://xueqiu.com/{XUEQIU_USER_ID}/{item_id}",
                collected_at=collected_at,
                verification="本人发布",
                summary_status="source",
                summary_basis="本人原文摘录",
            )
        )
    return results


def fetch_xueqiu(fetch: Callable[..., bytes], collected_at: str) -> tuple[list[FeedItem], dict[str, str]]:
    cookie = os.environ.get("XUEQIU_COOKIE", "").strip()
    if not cookie:
        return [], source_state(
            "xueqiu",
            "雪球本人账号",
            "setup",
            f"设置 XUEQIU_COOKIE 后采集动态；公开主页：{XUEQIU_PROFILE}",
            collected_at,
        )
    url = (
        "https://xueqiu.com/statuses/search.json?"
        f"count=20&comment=0&hl=0&source=user&sort=time&page=1&q=&type=0&user_id={XUEQIU_USER_ID}"
    )
    try:
        data = fetch(
            url,
            {
                "Accept": "application/json",
                "Cookie": cookie,
                "Referer": XUEQIU_PROFILE,
            },
        )
        items = parse_xueqiu(json.loads(data), collected_at)
        return items, source_state("xueqiu", "雪球本人账号", "ok", f"获取 {len(items)} 条本人动态", collected_at)
    except Exception as exc:
        return [], source_state("xueqiu", "雪球本人账号", "error", f"读取失败：{exc}", collected_at)


def source_state(key: str, name: str, status: str, detail: str, checked_at: str) -> dict[str, str]:
    return {"key": key, "name": name, "status": status, "detail": detail, "checked_at": checked_at}


def load_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


def response_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"]).strip()
    for output in payload.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"]).strip()
    choices = payload.get("choices", [])
    if choices and choices[0].get("message", {}).get("content"):
        return str(choices[0]["message"]["content"]).strip()
    content = payload.get("content", [])
    if content:
        return "\n".join(str(block["text"]).strip() for block in content if block.get("type") == "text" and block.get("text")).strip()
    return ""


def response_citations(payload: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    known_urls: set[str] = set()
    for output in payload.get("output", []):
        for content in output.get("content", []):
            for annotation in content.get("annotations", []):
                if annotation.get("type") != "url_citation" or not annotation.get("url"):
                    continue
                if annotation["url"] in known_urls:
                    continue
                known_urls.add(annotation["url"])
                citations.append({
                    "url": annotation["url"],
                    "title": annotation.get("title", "摘要引用来源"),
                })
    return citations[:3]


def response_error_detail(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or error.get("code")
        if message:
            return text_only(str(message))[:120]
    elif error:
        return text_only(str(error))[:120]
    fields = ", ".join(sorted(str(key) for key in payload.keys()))
    return f"响应无文本字段；字段：{fields or '无'}"


def summarize_media_items(
    items: list[dict[str, Any]],
    fetch: Callable[..., bytes] = request_bytes,
    post: Callable[..., dict[str, Any]] = post_json,
) -> dict[str, str] | None:
    anthropic_key = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    )
    api_key = os.environ.get("SUMMARY_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    use_anthropic = bool(anthropic_key and ANTHROPIC_BASE_URL)
    if use_anthropic and not ANTHROPIC_MODEL:
        return {"status": "setup", "detail": "已配置 Anthropic 兼容接口；请设置 ANTHROPIC_MODEL 后生成摘要"}
    if use_anthropic:
        api_key = anthropic_key
    pending = [
        item for item in items
        if item.get("source_type") == "媒体报道" and item.get("summary_status") != "ai"
    ][:SUMMARY_LIMIT]
    if not api_key:
        return None
    succeeded = 0
    failed = 0
    failure_reason = ""
    for item in pending:
        description = ""
        try:
            description = meta_description(fetch(item["url"], {"Accept": "text/html"}))
        except Exception:
            pass
        material = (
            f"标题：{item['title']}\n来源：{item['source']}\n页面描述：{description}"
            if description
            else f"标题：{item['title']}\n来源：{item['source']}\n未能读取文章正文或页面描述。"
        )
        prompt = (
            "你在为公开投资动态看板生成摘要。只使用输入材料，不推断交易事实，不提供投资建议。"
            "若需要搜索，请检索并核对与标题对应的报道；没有足够证据时明确说无法核实。"
            "若仅能依赖标题，必须以“标题显示”开头；若找到页面材料，必须以“据报道”开头。"
            "使用简体中文，最多两句、90字以内。\n\n" + material
        )
        try:
            if use_anthropic:
                endpoint = f"{ANTHROPIC_BASE_URL}/v1/messages"
                request_payload = {
                    "model": ANTHROPIC_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 160,
                }
                auth_headers = {
                    "anthropic-version": "2023-06-01",
                }
                if ANTHROPIC_AUTH_STYLE == "bearer":
                    auth_headers["Authorization"] = f"Bearer {api_key}"
                else:
                    auth_headers["x-api-key"] = api_key
                provider_style = "anthropic_messages"
            elif SUMMARY_API_STYLE == "chat_completions":
                endpoint = f"{SUMMARY_API_BASE_URL}/chat/completions"
                request_payload: dict[str, Any] = {
                    "model": SUMMARY_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 160,
                }
                auth_headers = {"Authorization": f"Bearer {api_key}"}
                provider_style = SUMMARY_API_STYLE
            else:
                endpoint = f"{SUMMARY_API_BASE_URL}/responses"
                request_payload = {
                    "model": SUMMARY_MODEL,
                    "input": prompt,
                    "max_output_tokens": 160,
                }
                if not description and SUMMARY_SUPPORTS_WEB_SEARCH:
                    request_payload.update({
                        "tools": [{"type": "web_search"}],
                        "tool_choice": "auto",
                        "include": ["web_search_call.action.sources"],
                    })
                auth_headers = {"Authorization": f"Bearer {api_key}"}
                provider_style = SUMMARY_API_STYLE
            result = post(
                endpoint,
                request_payload,
                auth_headers,
            )
            summary = response_text(result)
            if not summary:
                raise ValueError(response_error_detail(result))
            citations = response_citations(result)
            item["summary"] = summary
            item["summary_status"] = "ai"
            item["summary_basis"] = f"AI 摘要 · {'页面描述' if description else '联网核验' if citations else '仅标题'}"
            item["summary_model"] = ANTHROPIC_MODEL if use_anthropic else SUMMARY_MODEL
            item["summary_provider_style"] = provider_style
            item["summary_citations"] = citations
            succeeded += 1
        except Exception as exc:
            failed += 1
            if not failure_reason:
                failure_reason = f"{type(exc).__name__}"
                if isinstance(exc, HTTPError):
                    failure_reason += f" HTTP {exc.code}"
                elif str(exc):
                    failure_reason += f": {text_only(str(exc))[:120]}"
    if not pending:
        return {"status": "ok", "detail": "没有待总结的新增媒体条目"}
    suffix = f"（首次失败：{failure_reason}）" if failure_reason else ""
    return {"status": "ok" if succeeded else "error", "detail": f"AI 总结 {succeeded} 条，失败 {failed} 条{suffix}"}


def normalized_existing(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("source_type") == "媒体报道":
        item.setdefault("summary_status", "pending")
        item.setdefault("summary_basis", "等待 AI 摘要")
    else:
        item.setdefault("summary_status", "source")
        item.setdefault("summary_basis", "来源摘要")
    return item


def build_feed(output: Path, fetch: Callable[..., bytes] = request_bytes) -> dict[str, Any]:
    collected_at = now_iso()
    current_items: list[FeedItem] = []
    states: list[dict[str, str]] = []
    for collector in (fetch_xueqiu, fetch_sec, fetch_google_news):
        items, state = collector(fetch, collected_at)
        current_items.extend(items)
        states.append(state)

    merged: dict[str, dict[str, Any]] = {item["id"]: normalized_existing(item) for item in load_existing(output)}
    for item in current_items:
        current = asdict(item)
        previous = merged.get(item.id)
        if previous and previous.get("summary_status") == "ai":
            current.update({
                key: previous[key]
                for key in ("summary", "summary_status", "summary_basis", "summary_model", "summary_provider_style", "summary_citations")
                if key in previous
            })
        merged[item.id] = current
    items = sorted(merged.values(), key=lambda item: item["published_at"], reverse=True)[:500]
    summary_state = summarize_media_items(items, fetch)
    if summary_state:
        states.append(
            source_state("summary", "AI 自动摘要", summary_state["status"], summary_state["detail"], collected_at)
        )
    else:
        states.append(
            source_state("summary", "AI 自动摘要", "setup", "设置 Anthropic / SUMMARY_API_KEY / OPENAI_API_KEY 后逐批生成媒体摘要", collected_at)
        )
    return {
        "updated_at": collected_at,
        "profile": {
            "name": "段永平",
            "xueqiu_name": "大道无形我有型",
            "xueqiu_url": XUEQIU_PROFILE,
            "sec_entity": "H&H International Investment, LLC",
        },
        "sources": states,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="采集段永平公开动态并生成静态站点数据")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON 输出路径")
    args = parser.parse_args()
    feed = build_feed(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok_count = sum(source["status"] == "ok" for source in feed["sources"])
    print(f"写入 {len(feed['items'])} 条记录，{ok_count} 个来源读取成功：{args.output}")
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
