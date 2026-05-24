import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import collect


NEWS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss><channel><item>
<title>\xe6\xae\xb5\xe6\xb0\xb8\xe5\xb9\xb3\xe5\x8a\xa0\xe4\xbb\x93\xe8\x8b\xb1\xe4\xbc\x9f\xe8\xbe\xbe - \xe7\xa4\xba\xe4\xbe\x8b\xe8\xb4\xa2\xe7\xbb\x8f</title>
<link>https://example.test/news/1</link>
<pubDate>Wed, 20 May 2026 08:01:00 GMT</pubDate>
<source>\xe7\xa4\xba\xe4\xbe\x8b\xe8\xb4\xa2\xe7\xbb\x8f</source>
</item></channel></rss>"""


class CollectorTests(unittest.TestCase):
    def test_transient_http_failure_is_retried(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"ok"

        failure = HTTPError("https://example.test", 503, "busy", {}, None)
        with patch.object(collect, "urlopen", side_effect=[failure, Response()]) as mocked, patch.object(
            collect.time, "sleep"
        ):
            self.assertEqual(collect.request_bytes("https://example.test"), b"ok")
        self.assertEqual(mocked.call_count, 2)

    def test_google_news_is_classified_as_reported_investment(self):
        items = collect.parse_google_news(NEWS_XML, "2026-05-23T00:00:00Z")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "investment")
        self.assertEqual(items[0].verification, "需核验")
        self.assertEqual(items[0].source_type, "媒体报道")
        self.assertEqual(items[0].summary_status, "pending")
        self.assertEqual(collect.classify_news("段永平重仓某公司并继续押注赛道"), "investment")
        self.assertEqual(collect.classify_news("段永平重估英伟达"), "investment")
        self.assertEqual(collect.classify_news("段永平回复网友：买的是生意"), "interview")

    def test_sec_filings_become_original_disclosure_items(self):
        payload = {
            "filings": {
                "recent": {
                    "form": ["13F-HR", "N-PX"],
                    "accessionNumber": ["0001759760-26-000005", "skip"],
                    "filingDate": ["2026-05-19", "2026-01-01"],
                    "reportDate": ["2026-03-31", "2025-12-31"],
                    "primaryDocument": ["xslForm13F_X02/primary_doc.xml", "ignored.xml"],
                }
            }
        }
        items = collect.parse_sec(payload, "2026-05-23T00:00:00Z")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].verification, "原始披露")
        self.assertIn("2026-03-31", items[0].summary)

    def test_sec_is_not_requested_without_contact_user_agent(self):
        with patch.dict(os.environ, {}, clear=True):
            items, status = collect.fetch_sec(lambda *_args: b"", "2026-05-23T00:00:00Z")
        self.assertEqual(items, [])
        self.assertEqual(status["status"], "setup")

    def test_ai_summary_uses_extracted_page_description(self):
        items = [
            {
                "id": "news-1",
                "title": "段永平加仓英伟达",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/1",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_fetch(_url, _headers=None):
            return '<meta name="description" content="文章讨论一项已经披露的季度末持仓变化以及公开数据来源。">'.encode()

        def fake_post(_url, payload, _headers=None):
            captured["input"] = payload["input"]
            return {"output": [{"content": [{"type": "output_text", "text": "据报道，文章讨论公开披露中的持仓变化。"}]}]}

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            status = collect.summarize_media_items(items, fake_fetch, fake_post)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(items[0]["summary_status"], "ai")
        self.assertIn("页面描述", items[0]["summary_basis"])
        self.assertIn("已经披露", captured["input"])

    def test_ai_summary_searches_and_stores_citations_without_description(self):
        items = [
            {
                "id": "news-2",
                "title": "段永平最新公开观点",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/2",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_post(_url, payload, _headers=None):
            captured.update(payload)
            return {
                "output": [{
                    "content": [{
                        "type": "output_text",
                        "text": "据报道，文章梳理了公开观点。",
                        "annotations": [{
                            "type": "url_citation",
                            "title": "示例财经原文",
                            "url": "https://example.test/source",
                        }],
                    }]
                }]
            }

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertEqual(captured["tools"], [{"type": "web_search"}])
        self.assertIn("联网核验", items[0]["summary_basis"])
        self.assertEqual(items[0]["summary_citations"][0]["url"], "https://example.test/source")

    def test_compatible_summary_api_can_disable_web_search(self):
        items = [
            {
                "id": "news-3",
                "title": "段永平公开动态",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/3",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_post(url, payload, headers=None):
            captured.update({"url": url, "payload": payload, "headers": headers})
            return {"output_text": "标题显示，该报道提及段永平公开动态。"}

        with patch.dict(
            os.environ,
            {
                "SUMMARY_API_KEY": "provider-key",
                "SUMMARY_API_BASE_URL": "https://proxy.example/v1",
                "SUMMARY_API_STYLE": "responses",
                "SUMMARY_SUPPORTS_WEB_SEARCH": "false",
            },
            clear=True,
        ), patch.object(collect, "SUMMARY_API_BASE_URL", "https://proxy.example/v1"), patch.object(
            collect, "SUMMARY_API_STYLE", "responses"
        ), patch.object(
            collect, "SUMMARY_SUPPORTS_WEB_SEARCH", False
        ):
            collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertEqual(captured["url"], "https://proxy.example/v1/responses")
        self.assertNotIn("tools", captured["payload"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer provider-key")

    def test_chat_completions_provider_is_supported(self):
        items = [
            {
                "id": "news-4",
                "title": "段永平新闻",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/4",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_post(url, payload, _headers=None):
            captured.update({"url": url, "payload": payload})
            return {"choices": [{"message": {"content": "标题显示，该报道涉及公开动态。"}}]}

        with patch.dict(os.environ, {"SUMMARY_API_KEY": "provider-key"}, clear=True), patch.object(
            collect, "SUMMARY_API_BASE_URL", "https://proxy.example/v1"
        ), patch.object(collect, "SUMMARY_API_STYLE", "chat_completions"):
            collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertEqual(captured["url"], "https://proxy.example/v1/chat/completions")
        self.assertIn("messages", captured["payload"])
        self.assertEqual(items[0]["summary_status"], "ai")

    def test_anthropic_compatible_provider_is_supported(self):
        items = [
            {
                "id": "news-5",
                "title": "段永平新闻",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/5",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_post(url, payload, headers=None):
            captured.update({"url": url, "payload": payload, "headers": headers})
            return {"content": [{"type": "text", "text": "标题显示，该报道涉及公开动态。"}]}

        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "glm-key"}, clear=True), patch.object(
            collect, "ANTHROPIC_BASE_URL", "https://bobdong.cn"
        ), patch.object(collect, "ANTHROPIC_MODEL", "glm-model"), patch.object(
            collect, "ANTHROPIC_AUTH_STYLE", "x-api-key"
        ):
            collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertEqual(captured["url"], "https://bobdong.cn/v1/messages")
        self.assertEqual(captured["headers"]["x-api-key"], "glm-key")
        self.assertEqual(captured["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(items[0]["summary_provider_style"], "anthropic_messages")

    def test_anthropic_gateway_can_use_bearer_auth(self):
        items = [
            {
                "id": "news-6",
                "title": "段永平新闻",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/6",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]
        captured = {}

        def fake_post(_url, _payload, headers=None):
            captured["headers"] = headers
            return {"content": [{"type": "text", "text": "标题显示，该报道涉及公开动态。"}]}

        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "glm-key"}, clear=True), patch.object(
            collect, "ANTHROPIC_BASE_URL", "https://bobdong.cn"
        ), patch.object(collect, "ANTHROPIC_MODEL", "GLM-5.1"), patch.object(
            collect, "ANTHROPIC_AUTH_STYLE", "bearer"
        ):
            collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer glm-key")
        self.assertNotIn("x-api-key", captured["headers"])

    def test_summary_error_reports_safe_gateway_message(self):
        items = [
            {
                "id": "news-error",
                "title": "段永平新闻",
                "source": "示例财经",
                "source_type": "媒体报道",
                "url": "https://example.test/news/error",
                "summary_status": "pending",
                "summary": "等待自动摘要",
            }
        ]

        def fake_post(_url, _payload, headers=None):
            return {"error": {"message": "model not found", "type": "invalid_request"}}

        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "glm-key"}, clear=True), patch.object(
            collect, "ANTHROPIC_BASE_URL", "https://bobdong.cn"
        ), patch.object(collect, "ANTHROPIC_MODEL", "GLM-5.1"):
            result = collect.summarize_media_items(items, lambda *_args: b"<html></html>", fake_post)
        self.assertIn("ValueError: model not found", result["detail"])

    def test_anthropic_provider_requires_a_model(self):
        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "glm-key"}, clear=True), patch.object(
            collect, "ANTHROPIC_BASE_URL", "https://bobdong.cn"
        ), patch.object(collect, "ANTHROPIC_MODEL", ""):
            result = collect.summarize_media_items([], lambda *_args: b"", lambda *_args: {})
        self.assertEqual(result["status"], "setup")
        self.assertIn("ANTHROPIC_MODEL", result["detail"])

    def test_xueqiu_is_not_requested_without_cookie(self):
        with patch.dict(os.environ, {}, clear=True):
            items, status = collect.fetch_xueqiu(lambda *_args: b"", "2026-05-23T00:00:00Z")
        self.assertEqual(items, [])
        self.assertEqual(status["status"], "setup")

    def test_build_feed_merges_previous_records(self):
        sec_payload = {
            "filings": {
                "recent": {
                    "form": ["13F-HR"],
                    "accessionNumber": ["0001759760-26-000005"],
                    "filingDate": ["2026-05-19"],
                    "reportDate": ["2026-03-31"],
                    "primaryDocument": ["primary_doc.xml"],
                }
            }
        }

        def fake_fetch(url, _headers=None):
            if "sec.gov" in url:
                return json.dumps(sec_payload).encode()
            return NEWS_XML

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"TRACKER_USER_AGENT": "DadaoTracker test@example.com"}, clear=True
        ):
            path = Path(directory) / "feed.json"
            path.write_text('{"items":[{"id":"old","published_at":"2025-01-01T00:00:00Z"}]}')
            feed = collect.build_feed(path, fake_fetch)
        self.assertIn("old", {item["id"] for item in feed["items"]})
        self.assertEqual(sum(source["status"] == "ok" for source in feed["sources"]), 2)


if __name__ == "__main__":
    unittest.main()
