import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


NEWS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss><channel><item>
<title>\xe6\xae\xb5\xe6\xb0\xb8\xe5\xb9\xb3\xe5\x8a\xa0\xe4\xbb\x93\xe8\x8b\xb1\xe4\xbc\x9f\xe8\xbe\xbe - \xe7\xa4\xba\xe4\xbe\x8b\xe8\xb4\xa2\xe7\xbb\x8f</title>
<link>https://example.test/news/1</link>
<pubDate>Wed, 20 May 2026 08:01:00 GMT</pubDate>
<source>\xe7\xa4\xba\xe4\xbe\x8b\xe8\xb4\xa2\xe7\xbb\x8f</source>
</item></channel></rss>"""


class CollectorTests(unittest.TestCase):
    def test_google_news_is_classified_as_reported_investment(self):
        items = collect.parse_google_news(NEWS_XML, "2026-05-23T00:00:00Z")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "investment")
        self.assertEqual(items[0].verification, "需核验")
        self.assertEqual(items[0].source_type, "媒体报道")
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
