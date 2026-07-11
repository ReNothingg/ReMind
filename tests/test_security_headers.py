from flask import Flask

from utils.security_headers import apply_security_headers


def test_html_preview_uses_its_isolated_csp_and_can_be_framed_by_the_app():
    app = Flask(__name__)

    with app.test_request_context("/html-preview.html"):
        response = apply_security_headers(app.make_response(""))

    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'unsafe-inline' 'unsafe-eval' data: blob:" in csp
    assert "frame-src 'self' data: blob:" in csp
    assert "connect-src 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_regular_responses_keep_the_strict_application_csp():
    app = Flask(__name__)

    with app.test_request_context("/"):
        response = apply_security_headers(app.make_response(""))

    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in response.headers["Content-Security-Policy"].split("style-src", 1)[0]
    assert response.headers["X-Frame-Options"] == "DENY"
