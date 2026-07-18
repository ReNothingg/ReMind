from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.web_search import (
    build_source_from_candidate,
    build_search_query_variants,
    collect_web_search_candidates,
    requested_period_score,
    run_web_search,
    score_search_candidate,
    score_web_source,
)


class WebSearchQualityTests(unittest.TestCase):
    def test_openai_query_gets_an_official_site_variant(self) -> None:
        variants = build_search_query_variants("OpenAI latest news July 2026")

        self.assertTrue(any("site:openai.com" in variant for variant in variants))

    def test_official_and_trusted_sources_outrank_generic_results(self) -> None:
        query = "OpenAI latest news July 2026"
        official = {
            "title": "OpenAI News July 2026",
            "url": "https://openai.com/news/",
            "snippet": "Official OpenAI announcements from July 2026.",
            "search_rank": 3,
            "query_variant_index": 1,
            "published_at": "2026-07-16T12:00:00Z",
        }
        generic = {
            "title": "OpenAI latest news July 2026",
            "url": "https://random-seo.example/openai-news",
            "snippet": "A roundup of OpenAI stories.",
            "search_rank": 1,
            "query_variant_index": 0,
            "published_at": "2024-01-01T12:00:00Z",
        }

        self.assertGreater(
            score_search_candidate(official, query),
            score_search_candidate(generic, query),
        )

    def test_requested_month_penalizes_an_older_article(self) -> None:
        query = "OpenAI latest news July 2026"

        self.assertGreater(
            requested_period_score("2026-07-17T12:00:00Z", query),
            requested_period_score("2026-05-29T12:00:00Z", query),
        )

    def test_time_sensitive_search_combines_news_and_web_results(self) -> None:
        query = "OpenAI latest news July 2026"
        news_result = {
            "title": "OpenAI launches a new model",
            "url": "https://www.reuters.com/technology/openai-launch/",
            "snippet": "A current independent report about OpenAI.",
            "published_at": "2026-07-17T12:00:00Z",
            "result_type": "news",
        }

        with (
            patch("services.web_search.google_news_rss_search", return_value=[]),
            patch(
                "services.web_search.web_search_news_free",
                return_value=[news_result],
            ) as news_search,
            patch("services.web_search.web_search_free", return_value=[]),
        ):
            candidates = collect_web_search_candidates(query)

        self.assertEqual(news_search.call_count, 4)
        news_search.assert_any_call(query, max_results=None)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["result_type"], "news")
        self.assertEqual(candidates[0]["url"], news_result["url"])

    def test_robots_blocked_news_keeps_search_metadata_without_fetching_page(self) -> None:
        candidate = {
            "title": "OpenAI update",
            "url": "https://www.reuters.com/technology/openai-update/",
            "snippet": "Reuters reports a current OpenAI update.",
            "published_at": "2026-07-17T12:00:00Z",
            "search_rank": 1,
            "query_variant_index": 0,
            "matched_queries": ["OpenAI latest news"],
            "result_type": "news",
        }

        with (
            patch("services.web_search.is_public_http_url", return_value=True),
            patch("services.web_search.robots_txt_allows", return_value=False),
            patch("services.web_search.fetch_full_page") as fetch_page,
        ):
            source = build_source_from_candidate(candidate, "OpenAI latest news")

        fetch_page.assert_not_called()
        self.assertIsNotNone(source)
        self.assertEqual(source["error"], "robots_disallowed")
        self.assertEqual(source["snippet"], candidate["snippet"])

    def test_rss_news_uses_publisher_metadata_without_opening_google_page(self) -> None:
        candidate = {
            "title": "OpenAI update - Reuters",
            "url": "https://news.google.com/rss/articles/example",
            "snippet": "Reuters reports a current OpenAI update.",
            "published_at": "Thu, 17 Jul 2026 12:00:00 GMT",
            "search_rank": 1,
            "query_variant_index": 0,
            "matched_queries": ["OpenAI latest news"],
            "result_type": "news_rss",
            "publisher_url": "https://www.reuters.com/",
            "site_name": "Reuters",
            "display_url": "reuters.com",
            "favicon_url": "https://www.reuters.com/favicon.ico",
        }

        with (
            patch("services.web_search.is_public_http_url", return_value=True),
            patch("services.web_search.robots_txt_allows") as robots_allowed,
            patch("services.web_search.fetch_full_page") as fetch_page,
        ):
            source = build_source_from_candidate(candidate, "OpenAI latest news")

        robots_allowed.assert_not_called()
        fetch_page.assert_not_called()
        self.assertIsNotNone(source)
        self.assertEqual(source["site_name"], "Reuters")
        self.assertEqual(source["authority_url"], candidate["publisher_url"])

    def test_news_search_has_no_fixed_source_cap_and_filters_low_quality_results(self) -> None:
        query = "OpenAI latest news July 2026"
        published_at = datetime.now(timezone.utc).isoformat()
        trusted_results = [
            ("OpenAI News", "https://openai.com/news/"),
            ("OpenAI update", "https://www.reuters.com/technology/openai-update/"),
            ("OpenAI report", "https://www.ft.com/content/openai-report"),
            ("OpenAI launch", "https://techcrunch.com/openai-launch/"),
            ("OpenAI coverage", "https://www.theverge.com/openai-coverage"),
            ("OpenAI briefing", "https://www.bloomberg.com/news/openai-briefing"),
            ("OpenAI announcement", "https://apnews.com/article/openai-announcement"),
            ("OpenAI analysis", "https://www.bbc.com/news/articles/openai-analysis"),
        ]
        candidates = [
            {
                "title": title,
                "url": url,
                "snippet": "OpenAI news confirmed in July 2026.",
                "published_at": published_at,
                "search_rank": index + 1,
                "query_variant_index": 0,
                "matched_queries": [query],
            }
            for index, (title, url) in enumerate(trusted_results)
        ]
        candidates.extend(
            {
                "title": f"OpenAI roundup {noise_index}",
                "url": f"https://noise-{noise_index}.example/post",
                "snippet": "Unverified OpenAI roundup.",
                "published_at": "2024-01-01T12:00:00Z",
                "search_rank": len(trusted_results) + noise_index + 1,
                "query_variant_index": 0,
                "matched_queries": [query],
            }
            for noise_index in range(20)
        )

        def build_source(candidate: dict, search_query: str) -> dict:
            source = {
                **candidate,
                "final_url": candidate["url"],
                "site_name": candidate["url"].split("/")[2].removeprefix("www."),
                "display_url": candidate["url"],
                "ok": True,
                "text": "OpenAI news confirmed by this source in July 2026.",
                "error": None,
                "favicon_url": None,
            }
            source["score"] = score_web_source(source, search_query)
            return source

        with (
            patch(
                "services.web_search.collect_web_search_candidates",
                return_value=candidates,
            ),
            patch(
                "services.web_search.build_source_from_candidate",
                side_effect=build_source,
            ),
        ):
            result = run_web_search(query)

        urls = [source["url"] for source in result["sources"]]
        self.assertGreater(len(urls), 5)
        self.assertIn("https://openai.com/news/", urls)
        self.assertFalse(any("noise-" in url for url in urls))


if __name__ == "__main__":
    unittest.main()
