from __future__ import annotations

import json
import secrets

from flask import (
    Response,
    g,
    jsonify,
    session,
    url_for,
)

from backend.auth.apple import (
    _apple_web_client_credentials_available,
    _valid_apple_web_redirect_uri,
)
from backend.auth.telegram import _issue_telegram_login_nonce
from backend.db.models import User, db


def register_config_routes(app):
    @app.route("/api/auth/check", methods=["GET"])
    def api_check_auth():

        if "user_id" in session:
            user = db.session.get(User, session["user_id"])
            if user:
                return jsonify({"authenticated": True, "user": user.to_dict()}), 200
        return jsonify({"authenticated": False, "user": None}), 200

    @app.route("/api/auth/turnstile/mobile", methods=["GET"])
    def api_mobile_turnstile():

        from backend.config import LOCALHOST_MODE, TURNSTILE_SITE_KEY

        nonce = getattr(g, "csp_nonce", "") or secrets.token_urlsafe(24)
        site_key = TURNSTILE_SITE_KEY if TURNSTILE_SITE_KEY and not LOCALHOST_MODE else ""
        site_key_literal = json.dumps(site_key)
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <style nonce="{nonce}">
    :root {{ color-scheme: light dark; }}
    html, body {{ margin: 0; min-height: 74px; background: transparent; overflow: hidden; }}
    body {{ display: flex; align-items: center; justify-content: center; }}
    #challenge {{ min-height: 70px; width: 100%; display: flex; align-items: center; justify-content: center; }}
  </style>
  <script nonce="{nonce}">
    (() => {{
      const siteKey = {site_key_literal};
      const post = (payload) => {{
        try {{ window.webkit?.messageHandlers?.turnstile?.postMessage(payload); }} catch (_) {{}}
      }};
      let timeout = setTimeout(() => post({{ state: "failed" }}), 20000);
      window.remindTurnstileBoot = () => {{
        if (!siteKey) {{
          clearTimeout(timeout);
          post({{ state: "disabled" }});
          return;
        }}
        if (!window.turnstile) {{
          clearTimeout(timeout);
          post({{ state: "failed" }});
          return;
        }}
        try {{
          window.turnstile.render("#challenge", {{
            sitekey: siteKey,
            theme: "auto",
            callback: (token) => {{ clearTimeout(timeout); post({{ state: "solved", token }}); }},
            "expired-callback": () => post({{ state: "expired" }}),
            "error-callback": () => {{ clearTimeout(timeout); post({{ state: "failed" }}); }}
          }});
          post({{ state: "ready" }});
        }} catch (_) {{
          clearTimeout(timeout);
          post({{ state: "failed" }});
        }}
      }};
    }})();
  </script>
  <script nonce="{nonce}" defer src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&amp;onload=remindTurnstileBoot"></script>
</head>
<body><main id="challenge"></main></body>
</html>"""
        response = Response(document, content_type="text/html; charset=utf-8")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}' https://challenges.cloudflare.com; "
            f"style-src 'nonce-{nonce}'; "
            "frame-src https://challenges.cloudflare.com; "
            "connect-src https://challenges.cloudflare.com; "
            "img-src data: https://challenges.cloudflare.com; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return response

    @app.route("/api/auth/config", methods=["GET"])
    def api_auth_config():

        from backend.config import (
            ALLOWED_HOSTS,
            APPLE_APP_BUNDLE_ID,
            APPLE_CLIENT_SECRET,
            APPLE_KEY_ID,
            APPLE_PRIVATE_KEY,
            APPLE_PRIVATE_KEY_PATH,
            APPLE_SERVICE_ID,
            APPLE_TEAM_ID,
            APPLE_WEB_REDIRECT_URI,
            GOOGLE_CLIENT_ID,
            IOS_OAUTH_CALLBACK_SCHEME,
            IOS_OAUTH_REDIRECT_URI,
            LOCALHOST_MODE,
            TELEGRAM_BOT_USERNAME,
            TELEGRAM_CLIENT_ID,
            TURNSTILE_SITE_KEY,
        )

        telegram_nonce = _issue_telegram_login_nonce() if TELEGRAM_CLIENT_ID else None
        apple_web_available = bool(
            _valid_apple_web_redirect_uri(APPLE_WEB_REDIRECT_URI, ALLOWED_HOSTS)
            and _apple_web_client_credentials_available(
                service_id=APPLE_SERVICE_ID,
                client_secret=APPLE_CLIENT_SECRET,
                team_id=APPLE_TEAM_ID,
                key_id=APPLE_KEY_ID,
                private_key=APPLE_PRIVATE_KEY,
                private_key_path=APPLE_PRIVATE_KEY_PATH,
            )
        )

        return (
            jsonify(
                {
                    "turnstile_site_key": TURNSTILE_SITE_KEY,
                    "turnstile_required": bool(TURNSTILE_SITE_KEY) and not LOCALHOST_MODE,
                    "gauth_available": bool(GOOGLE_CLIENT_ID),
                    "google_login_url": url_for("login_google"),
                    "google_mobile_login_url": url_for("login_google", client="ios"),
                    "apple_native_available": bool(APPLE_APP_BUNDLE_ID),
                    "apple_web_available": apple_web_available,
                    "apple_login_url": url_for("login_apple") if apple_web_available else None,
                    "telegram_available": bool(TELEGRAM_CLIENT_ID),
                    "telegram_client_id": TELEGRAM_CLIENT_ID or None,
                    "telegram_nonce": telegram_nonce,
                    "telegram_bot_link_available": bool(TELEGRAM_BOT_USERNAME),
                    "mobile_oauth_redirect_uri": IOS_OAUTH_REDIRECT_URI,
                    "mobile_oauth_callback_scheme": IOS_OAUTH_CALLBACK_SCHEME,
                }
            ),
            200,
        )
