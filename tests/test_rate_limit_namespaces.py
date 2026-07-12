from flask import Flask, request

from utils.rate_limiting import RateLimiter


def test_rate_limiters_do_not_consume_each_others_budgets():
    app = Flask(__name__)
    app.secret_key = "test-only"
    chat = RateLimiter(max_requests=1, time_window=3600, use_redis=False, namespace="chat-test")
    drafts = RateLimiter(
        max_requests=1,
        time_window=3600,
        use_redis=False,
        namespace="draft-test",
    )

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.9"}):
        chat_identifier = chat.get_identifier(request)
        draft_identifier = drafts.get_identifier(request)
        assert chat.evaluate(chat_identifier).allowed is True
        assert chat.evaluate(chat_identifier).allowed is False
        assert drafts.evaluate(draft_identifier).allowed is True
