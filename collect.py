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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "feed.json"
SEC_CIK = "0001759760"
XUEQIU_USER_ID = "1247347556"
XUEQIU_PROFILE = f"https://xueqiu.com/u/{XUEQIU_USER_ID}"
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
    with urlopen(request, timeout=25, context=secure_context()) as response:
        return response.read()


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
            )
        )
    return results


def fetch_sec(fetch: Callable[..., bytes], collected_at: str) -> tuple[list[FeedItem], dict[str, str]]:
    url = f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json"
    try:
        payload = json.loads(fetch(url, {"Accept": "application/json"}))
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


def build_feed(output: Path, fetch: Callable[..., bytes] = request_bytes) -> dict[str, Any]:
    collected_at = now_iso()
    current_items: list[FeedItem] = []
    states: list[dict[str, str]] = []
    for collector in (fetch_xueqiu, fetch_sec, fetch_google_news):
        items, state = collector(fetch, collected_at)
        current_items.extend(items)
        states.append(state)

    merged: dict[str, dict[str, Any]] = {item["id"]: item for item in load_existing(output)}
    for item in current_items:
        merged[item.id] = asdict(item)
    items = sorted(merged.values(), key=lambda item: item["published_at"], reverse=True)[:500]
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
