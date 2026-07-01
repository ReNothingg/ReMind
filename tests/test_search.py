import routes.features.chat as chat_routes
import services.web_search as web_search
from utils.rate_limiting import rate_limit_store


def test_get_favicon_url_prefers_page_icon():
    html = '<html><head><link rel="shortcut icon" href="/assets/icon.svg"></head></html>'

    favicon = web_search.get_favicon_url("https://example.com/news/article", html)

    assert favicon == "https://example.com/assets/icon.svg"


def test_extract_text_from_html_removes_script_and_style():
    html = """
    <html>
      <head><title>Example title</title><style>.hidden{}</style></head>
      <body><script>alert(1)</script><main><h1>Hello</h1><p>World</p></main></body>
    </html>
    """

    text = web_search.extract_text_from_html(html)

    assert "Example title" in text
    assert "Hello" in text
    assert "World" in text
    assert "alert" not in text
    assert ".hidden" not in text


def test_robots_txt_allows_uses_specific_group_and_allow_precedence(monkeypatch):
    web_search._robots_policy_for_origin.cache_clear()

    class FakeResponse:
        status_code = 200
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, body):
            self.body = body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self.body

    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(
            "\n".join(
                [
                    "User-agent: ReMindBot",
                    "Disallow: /private",
                    "Allow: /private/public",
                    "",
                    "User-agent: *",
                    "Disallow: /",
                ]
            )
        )

    monkeypatch.setattr(web_search.requests, "get", fake_get)

    try:
        assert not web_search.robots_txt_allows("https://example.com/private/story")
        assert web_search.robots_txt_allows("https://example.com/private/public/story")
        assert web_search.robots_txt_allows("https://example.com/news")
        assert calls == ["https://example.com/robots.txt"]
    finally:
        web_search._robots_policy_for_origin.cache_clear()


def test_robots_txt_allows_when_robots_unavailable(monkeypatch):
    web_search._robots_policy_for_origin.cache_clear()

    def fake_get(*_args, **_kwargs):
        raise web_search.requests.RequestException("robots timeout")

    monkeypatch.setattr(web_search.requests, "get", fake_get)

    try:
        assert web_search.robots_txt_allows("https://example.com/news")
    finally:
        web_search._robots_policy_for_origin.cache_clear()


def test_fetch_full_page_skips_robots_disallowed_url(monkeypatch):
    monkeypatch.setattr(web_search, "robots_txt_allows", lambda _url, **_kwargs: False)

    def fail_get(*_args, **_kwargs):
        raise AssertionError("disallowed pages must not be fetched")

    monkeypatch.setattr(web_search.requests, "get", fail_get)

    result = web_search.fetch_full_page("https://93.184.216.34/private")

    assert result["ok"] is False
    assert result["error"] == "robots_txt_disallowed"
    assert result["text"] == ""


def test_fetch_full_page_blocks_private_redirect_target(monkeypatch):
    monkeypatch.setattr(web_search, "robots_txt_allows", lambda _url, **_kwargs: True)
    calls = []

    class FakeRedirectResponse:
        status_code = 302
        headers = {
            "Location": "http://127.0.0.1/admin",
            "content-type": "text/html",
        }
        is_redirect = True
        is_permanent_redirect = False
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

    def fake_get(url, **_kwargs):
        calls.append(url)
        return FakeRedirectResponse(url)

    monkeypatch.setattr(web_search.requests, "get", fake_get)

    result = web_search.fetch_full_page("https://93.184.216.34/start")

    assert calls == ["https://93.184.216.34/start"]
    assert result["ok"] is False
    assert result["error"] == "blocked_redirect_url"
    assert result["final_url"] == "http://127.0.0.1/admin"


def test_fetch_full_page_drops_private_favicon_url(monkeypatch):
    monkeypatch.setattr(web_search, "robots_txt_allows", lambda _url, **_kwargs: True)

    class FakeHtmlResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        is_redirect = False
        is_permanent_redirect = False
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.body = (
                '<html><head><link rel="icon" href="http://127.0.0.1/favicon.ico">'
                "</head><body>hello</body></html>"
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self.body

    monkeypatch.setattr(
        web_search.requests,
        "get",
        lambda url, **_kwargs: FakeHtmlResponse(url),
    )

    result = web_search.fetch_full_page("https://93.184.216.34/page")

    assert result["ok"] is True
    assert result["favicon_url"] is None
    assert result["text"] == "hello"


def test_run_web_search_skips_robots_disallowed_sources(monkeypatch):
    monkeypatch.setattr(web_search, "is_public_http_url", lambda _url, **_kwargs: True)
    monkeypatch.setattr(
        web_search,
        "web_search_free",
        lambda query, max_results: [
            {
                "title": "Blocked source",
                "url": "https://blocked.example/private",
                "snippet": "Blocked snippet",
            },
            {
                "title": "Allowed source",
                "url": "https://allowed.example/news",
                "snippet": "Allowed snippet",
            },
        ],
    )
    monkeypatch.setattr(
        web_search,
        "robots_txt_allows",
        lambda url, **_kwargs: "blocked.example" not in url,
    )
    fetched_urls = []

    def fake_fetch_full_page(url):
        fetched_urls.append(url)
        return {
            "ok": True,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "text": "Allowed full page text",
            "favicon_url": "https://allowed.example/favicon.ico",
            "error": None,
        }

    monkeypatch.setattr(web_search, "fetch_full_page", fake_fetch_full_page)

    result = web_search.run_web_search("latest news", max_results=2)

    assert fetched_urls == ["https://allowed.example/news"]
    assert len(result["sources"]) == 1
    assert result["sources"][0]["title"] == "Allowed source"
    assert "blocked.example" not in result["context"]
    assert "Blocked snippet" not in result["context"]


def test_run_web_search_builds_sources_and_model_context(monkeypatch):
    monkeypatch.setattr(web_search, "is_public_http_url", lambda _url, **_kwargs: True)
    monkeypatch.setattr(web_search, "robots_txt_allows", lambda _url, **_kwargs: True)
    monkeypatch.setattr(
        web_search,
        "web_search_free",
        lambda query, max_results: [
            {
                "title": "OpenAI news",
                "url": "https://example.com/openai",
                "snippet": "Short search snippet",
            }
        ],
    )
    monkeypatch.setattr(
        web_search,
        "fetch_full_page",
        lambda url: {
            "ok": True,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "text": "Full extracted page text",
            "favicon_url": "https://example.com/favicon.ico",
            "error": None,
        },
    )

    result = web_search.run_web_search("latest OpenAI news", max_results=1)

    assert result["query"] == "latest OpenAI news"
    assert result["sources"][0]["title"] == "OpenAI news"
    assert result["sources"][0]["site_name"] == "example.com"
    assert result["sources"][0]["favicon_url"] == "https://example.com/favicon.ico"
    assert "WEB SEARCH RESULTS" in result["context"]
    assert "https://example.com/openai" in result["context"]


def test_search_query_variants_expand_time_sensitive_queries(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, _timezone):
            class FakeNow:
                year = 2026

                def date(self):
                    return self

                def isoformat(self):
                    return "2026-06-11"

            return FakeNow()

    monkeypatch.setattr(web_search, "datetime", FakeDateTime)

    variants = web_search.build_search_query_variants("latest OpenAI news")

    assert variants == [
        "latest OpenAI news",
        "latest OpenAI news 2026",
        "latest OpenAI news official",
    ]


def test_canonical_search_url_key_removes_tracking_params():
    key = web_search.canonical_search_url_key(
        "https://www.example.com/news/?utm_source=x&b=2&a=1#section"
    )

    assert key == "https://example.com/news?a=1&b=2"


def test_run_web_search_reranks_sources_by_relevance(monkeypatch):
    monkeypatch.setattr(web_search, "is_public_http_url", lambda _url, **_kwargs: True)
    monkeypatch.setattr(web_search, "robots_txt_allows", lambda _url, **_kwargs: True)

    def fake_web_search_free(query, max_results):
        if query == "OpenAI latest model":
            return [
                {
                    "title": "Generic AI blog",
                    "url": "https://blog.example.com/post?utm_source=newsletter",
                    "snippet": "A broad roundup of technology links.",
                },
                {
                    "title": "OpenAI latest model announcement",
                    "url": "https://openai.com/news/model",
                    "snippet": "OpenAI latest model release details.",
                },
            ]
        return []

    def fake_fetch_full_page(url):
        if "openai.com" in url:
            return {
                "ok": True,
                "final_url": url,
                "status_code": 200,
                "content_type": "text/html",
                "text": "OpenAI latest model release with capabilities and availability details.",
                "favicon_url": "https://openai.com/favicon.ico",
                "error": None,
            }
        return {
            "ok": True,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "text": "Generic article about technology trends.",
            "favicon_url": "https://blog.example.com/favicon.ico",
            "error": None,
        }

    monkeypatch.setattr(web_search, "web_search_free", fake_web_search_free)
    monkeypatch.setattr(web_search, "fetch_full_page", fake_fetch_full_page)

    result = web_search.run_web_search("OpenAI latest model", max_results=2)

    assert [source["site_name"] for source in result["sources"]] == [
        "openai.com",
        "blog.example.com",
    ]
    assert result["sources"][0]["rank"] == 1


def test_build_web_search_augmented_message_wraps_context():
    payload = {
        "query": "query",
        "created_at": "2026-05-27T00:00:00+00:00",
        "sources": [
            {
                "rank": 1,
                "title": "Result",
                "url": "https://example.com/result",
                "final_url": "https://example.com/result",
                "site_name": "example.com",
                "snippet": "Snippet",
                "text": "Extract",
            }
        ],
    }

    message = web_search.build_web_search_augmented_message("Tell me", payload)

    assert message.startswith("Tell me")
    assert "<web_search_context>" in message
    assert "Do not invent URLs" in message


def test_auto_web_search_detects_current_fact_intent():
    assert web_search.should_auto_web_search("последние новости OpenAI")
    assert web_search.should_auto_web_search("What is the latest Gemini release?")
    assert web_search.explicit_web_search_requested(
        "последние новости openai. Используй поиск в интернете"
    )
    assert not web_search.should_auto_web_search("Напиши короткое стихотворение про осень")
    assert not web_search.should_auto_web_search("Ответь без интернета: что такое рекурсия?")


def test_auto_web_search_decider_uses_model_json(monkeypatch):
    monkeypatch.setattr(web_search, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        web_search,
        "_call_search_decision_model",
        lambda _prompt: '{"search": true, "query": "OpenAI latest news", "reason": "current facts"}',
    )

    decision = web_search.decide_auto_web_search("Tell me about OpenAI")

    assert decision == {
        "search": True,
        "query": "OpenAI latest news",
        "reason": "current facts",
        "source": "model",
    }


def test_auto_web_search_decider_respects_model_skip(monkeypatch):
    monkeypatch.setattr(web_search, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        web_search,
        "_call_search_decision_model",
        lambda _prompt: '```json\n{"search": "false", "query": "", "reason": "timeless"}\n```',
    )

    decision = web_search.decide_auto_web_search("Explain recursion")

    assert decision["search"] is False
    assert decision["query"] == "Explain recursion"
    assert decision["reason"] == "timeless"
    assert decision["source"] == "model"


def test_rewrite_web_search_query_uses_model_json(monkeypatch):
    monkeypatch.setattr(web_search, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        web_search,
        "_call_search_decision_model",
        lambda _prompt: '{"query": "OpenAI latest news May 2026", "reason": "clean search query"}',
    )

    rewrite = web_search.rewrite_web_search_query("Tell me the latest OpenAI news. Use web search.")

    assert rewrite == {
        "query": "OpenAI latest news May 2026",
        "reason": "clean search query",
        "source": "model",
    }


def test_chat_web_search_adds_sources_without_gemini_tooling(client, monkeypatch):
    rate_limit_store.clear()
    captured_queries = []

    def fake_run_search(query):
        captured_queries.append(query)
        return {
            "query": query,
            "created_at": "2026-05-27T00:00:00+00:00",
            "sources": [
                {
                    "rank": 1,
                    "title": "Search result",
                    "url": "https://example.com/search",
                    "final_url": "https://example.com/search",
                    "display_url": "example.com/search",
                    "site_name": "example.com",
                    "snippet": "A snippet",
                    "favicon_url": "https://example.com/favicon.ico",
                }
            ],
        }

    monkeypatch.setattr(
        chat_routes,
        "rewrite_web_search_query",
        lambda _query: {
            "query": "LLM rewritten manual query",
            "reason": "manual rewrite",
            "source": "model",
        },
    )
    monkeypatch.setattr(
        chat_routes,
        "run_web_search",
        fake_run_search,
    )
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {
            "reply": payload.get("message", ""),
        },
    )

    response = client.post(
        "/chat",
        json={"message": "find this", "model": "gemini", "webSearch": True},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["sources"][0]["site_name"] == "example.com"
    assert captured_queries == ["LLM rewritten manual query"]
    assert "<web_search_context>" in payload["reply"]
    assert "https://example.com/search" in payload["reply"]
    rate_limit_store.clear()


def test_chat_auto_web_search_adds_sources_for_current_query(client, monkeypatch):
    rate_limit_store.clear()
    captured_queries = []

    def fake_run_search(query):
        captured_queries.append(query)
        return {
            "query": query,
            "created_at": "2026-05-27T00:00:00+00:00",
            "sources": [
                {
                    "rank": 1,
                    "title": "Auto source",
                    "url": "https://example.com/auto",
                    "final_url": "https://example.com/auto",
                    "display_url": "example.com/auto",
                    "site_name": "example.com",
                    "snippet": "Auto snippet",
                    "favicon_url": "https://example.com/favicon.ico",
                }
            ],
        }

    monkeypatch.setattr(
        chat_routes,
        "decide_auto_web_search",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("obvious current queries should skip the LLM search decider")
        ),
    )
    monkeypatch.setattr(
        chat_routes,
        "rewrite_web_search_query",
        lambda _query: {
            "query": "OpenAI latest news",
            "reason": "fast auto rewrite",
            "source": "model",
        },
    )
    monkeypatch.setattr(
        chat_routes,
        "run_web_search",
        fake_run_search,
    )
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {
            "reply": payload.get("message", ""),
        },
    )

    response = client.post(
        "/chat",
        json={"message": "последние новости OpenAI", "model": "gemini", "autoWebSearch": True},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["sources"][0]["title"] == "Auto source"
    assert captured_queries == ["OpenAI latest news"]
    assert "<web_search_context>" in payload["reply"]
    rate_limit_store.clear()


def test_chat_form_auto_web_search_runs_for_explicit_search_request(client, monkeypatch):
    rate_limit_store.clear()
    captured_queries = []

    def fake_run_search(query):
        captured_queries.append(query)
        return {
            "query": query,
            "created_at": "2026-05-27T00:00:00+00:00",
            "sources": [
                {
                    "rank": 1,
                    "title": "Form auto source",
                    "url": "https://example.com/form-auto",
                    "final_url": "https://example.com/form-auto",
                    "display_url": "example.com/form-auto",
                    "site_name": "example.com",
                    "snippet": "Form auto snippet",
                    "favicon_url": "https://example.com/favicon.ico",
                }
            ],
        }

    monkeypatch.setattr(
        chat_routes,
        "decide_auto_web_search",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("explicit search requests must not call the auto decider")
        ),
    )
    monkeypatch.setattr(
        chat_routes,
        "rewrite_web_search_query",
        lambda _query: {
            "query": "OpenAI latest news",
            "reason": "explicit manual rewrite",
            "source": "model",
        },
    )
    monkeypatch.setattr(
        chat_routes,
        "run_web_search",
        fake_run_search,
    )
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {
            "reply": payload.get("message", ""),
        },
    )

    response = client.post(
        "/chat",
        data={
            "message": "последние новости openai. Используй поиск в интернете",
            "model": "gemini",
            "session_id": "form_auto_search",
            "history": "[]",
            "webSearch": "false",
            "autoWebSearch": "true",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["sources"][0]["title"] == "Form auto source"
    assert captured_queries == ["OpenAI latest news"]
    assert "<web_search_context>" in payload["reply"]
    assert "https://example.com/form-auto" in payload["reply"]
    rate_limit_store.clear()


def test_chat_auto_web_search_skips_static_query(client, monkeypatch):
    rate_limit_store.clear()

    def fail_search(_query):
        raise AssertionError("auto web search should not run for static creative prompts")

    monkeypatch.setattr(
        chat_routes,
        "decide_auto_web_search",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("obvious static queries should skip the LLM search decider")
        ),
    )
    monkeypatch.setattr(chat_routes, "run_web_search", fail_search)
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {
            "reply": payload.get("message", ""),
        },
    )

    response = client.post(
        "/chat",
        json={
            "message": "напиши короткое стихотворение про осень",
            "model": "gemini",
            "autoWebSearch": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "sources" not in payload
    assert "<web_search_context>" not in payload["reply"]
    rate_limit_store.clear()


def test_auth_settings_persist_automatic_web_search(client, create_confirmed_user, login):
    _user_id, email, password = create_confirmed_user()
    login_response = login(email, password)
    assert login_response.status_code == 200
    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_value

    update_response = client.put(
        "/api/auth/settings",
        json={"automatic_web_search": True},
        headers={"X-CSRF-Token": csrf_value},
    )

    assert update_response.status_code == 200
    assert update_response.get_json()["settings"]["automatic_web_search"] is True

    get_response = client.get("/api/auth/settings")
    assert get_response.status_code == 200
    assert get_response.get_json()["automatic_web_search"] is True


def test_chat_web_search_streams_progress_before_model_chunks(client, monkeypatch):
    rate_limit_store.clear()
    captured_queries = []

    def fake_run_search(query):
        captured_queries.append(query)
        return {
            "query": query,
            "created_at": "2026-05-27T00:00:00+00:00",
            "sources": [
                {
                    "rank": 1,
                    "title": "Streaming source",
                    "url": "https://example.com/live",
                    "final_url": "https://example.com/live",
                    "display_url": "example.com/live",
                    "site_name": "example.com",
                    "snippet": "Streaming snippet",
                    "favicon_url": "https://example.com/favicon.ico",
                }
            ],
        }

    monkeypatch.setattr(
        chat_routes,
        "rewrite_web_search_query",
        lambda _query: {
            "query": "streaming rewritten query",
            "reason": "manual stream rewrite",
            "source": "model",
        },
    )
    monkeypatch.setattr(
        chat_routes,
        "run_web_search",
        fake_run_search,
    )
    captured_payload = {}

    def fake_stream_model(_user_id, payload):
        captured_payload["message"] = payload.get("message", "")
        yield "The answer "
        yield {"reply_part": "arrives in chunks."}

    monkeypatch.setattr(chat_routes, "get_model_function", lambda _name: fake_stream_model)

    response = client.post(
        "/chat",
        json={"message": "find this live", "model": "gemini", "webSearch": True},
    )

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    assert body.index("web_search_querying") < body.index("web_search_started")
    assert body.index("web_search_started") < body.index("reply_part")
    assert "web_search_fetching" in body
    assert "web_search_done" in body
    assert '"sources"' in body
    assert '"query": "streaming rewritten query"' in body
    assert captured_queries == ["streaming rewritten query"]
    assert "The answer " in body
    assert "arrives in chunks." in body
    assert "<web_search_context>" in captured_payload["message"]
    assert "https://example.com/live" in captured_payload["message"]
    rate_limit_store.clear()


def test_chat_auto_web_search_skips_obvious_static_query_without_decider(client, monkeypatch):
    rate_limit_store.clear()

    def fail_search(_query):
        raise AssertionError("auto web search should not run when the model decider skips it")

    def fake_stream_model(_user_id, payload):
        yield {"reply_part": payload.get("message", "")}

    monkeypatch.setattr(
        chat_routes,
        "decide_auto_web_search",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("obvious static queries should not call the LLM search decider")
        ),
    )
    monkeypatch.setattr(chat_routes, "run_web_search", fail_search)
    monkeypatch.setattr(chat_routes, "get_model_function", lambda _name: fake_stream_model)

    response = client.post(
        "/chat",
        json={"message": "Explain recursion", "model": "gemini", "autoWebSearch": True},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "web_search_deciding" not in body
    assert "web_search_skipped" not in body
    assert "web_search_started" not in body
    assert "reply_part" in body
    assert "<web_search_context>" not in body
    rate_limit_store.clear()
