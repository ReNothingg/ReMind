import hashlib
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask

from utils import auth


@pytest.fixture()
def app():
    test_app = Flask(__name__)
    test_app.config.update(
        SECRET_KEY="apple-auth-test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    auth.db.init_app(test_app)
    with test_app.app_context():
        auth.db.create_all()
        yield test_app
        auth.db.session.remove()
        auth.db.drop_all()


def _apple_token(private_key, *, audience: str, nonce_hash: str, subject: str = "apple.subject.1"):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": auth.APPLE_ISSUER,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "exp": now + 86_400,
            "nonce": nonce_hash,
            "email": "person@example.com",
            "email_verified": "true",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_apple_challenge_is_digest_only_and_one_time(app):
    with app.app_context():
        challenge, raw_nonce = auth._issue_apple_auth_challenge(flow="native", mode="login")
        record = auth.AppleAuthChallenge.query.one()

        assert challenge not in record.challenge_hash
        assert raw_nonce not in record.nonce_hash
        assert record.challenge_hash == hashlib.sha256(challenge.encode()).hexdigest()
        assert record.nonce_hash == hashlib.sha256(raw_nonce.encode()).hexdigest()

        metadata = auth._consume_apple_auth_challenge(challenge, flow="native")
        assert metadata["nonce_hash"] == record.nonce_hash
        with pytest.raises(auth.AppleAuthError):
            auth._consume_apple_auth_challenge(challenge, flow="native")


def test_pending_apple_link_challenge_is_revoked_on_logout(app):
    with app.app_context():
        user = auth.User(
            username="link_owner",
            name="Link Owner",
            email="link-owner@example.com",
            password="unused",
            is_confirmed=True,
        )
        auth.db.session.add(user)
        auth.db.session.commit()
        challenge, _ = auth._issue_apple_auth_challenge(
            flow="web",
            mode="link",
            link_user_id=user.id,
        )

        auth._revoke_pending_apple_link_challenges(user.id)

        with pytest.raises(auth.AppleAuthError):
            auth._consume_apple_auth_challenge(challenge, flow="web")


def test_apple_web_binding_is_signed_scoped_and_expires():
    token = auth._encode_apple_web_binding("secret", "challenge-value")
    assert auth._decode_apple_web_binding("secret", token) == "challenge-value"
    assert auth._decode_apple_web_binding("other-secret", token) is None


def test_apple_web_callback_must_be_exact_and_same_site():
    callback = "https://chat.example.com/login/apple/callback"
    assert auth._valid_apple_web_redirect_uri(callback, ["chat.example.com"]) == callback
    assert (
        auth._valid_apple_web_redirect_uri(
            "https://attacker.example/login/apple/callback", ["chat.example.com"]
        )
        == ""
    )
    assert (
        auth._valid_apple_web_redirect_uri(
            "https://chat.example.com/login/apple/callback?next=elsewhere",
            ["chat.example.com"],
        )
        == ""
    )
    assert (
        auth._valid_apple_web_redirect_uri("https://chat.example.com/other", ["chat.example.com"])
        == ""
    )
    assert auth._normalize_redirect_target("/\\attacker.example", ["chat.example.com"]) == ""


def test_apple_identity_token_verification_and_replay_protection(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(
        auth,
        "_get_apple_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        ),
    )
    audience = "synvexai.remind"
    nonce_hash = hashlib.sha256(b"server-issued-nonce").hexdigest()
    identity_token = _apple_token(private_key, audience=audience, nonce_hash=nonce_hash)

    with app.app_context():
        claims = auth._verify_apple_identity_token(
            identity_token,
            audience=audience,
            expected_nonce_hash=nonce_hash,
        )
        assert claims["sub"] == "apple.subject.1"
        auth._consume_apple_token_replay(identity_token, claims)
        with pytest.raises(auth.AppleReplayError):
            auth._consume_apple_token_replay(identity_token, claims)


def test_apple_token_rejects_wrong_nonce(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "_get_apple_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())
        ),
    )
    identity_token = _apple_token(
        private_key,
        audience="synvexai.remind",
        nonce_hash=hashlib.sha256(b"different-nonce").hexdigest(),
    )

    with app.app_context(), pytest.raises(auth.AppleNonceMismatchError):
        auth._verify_apple_identity_token(
            identity_token,
            audience="synvexai.remind",
            expected_nonce_hash=hashlib.sha256(b"expected-nonce").hexdigest(),
        )


def test_apple_token_rejects_wrong_audience_and_algorithm(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "_get_apple_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())
        ),
    )
    nonce_hash = hashlib.sha256(b"server-issued-nonce").hexdigest()
    wrong_audience_token = _apple_token(
        private_key,
        audience="other.bundle",
        nonce_hash=nonce_hash,
    )
    weak_algorithm_token = jwt.encode(
        {"sub": "apple.subject.1"},
        "test-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )

    with app.app_context(), pytest.raises(jwt.InvalidAudienceError):
        auth._verify_apple_identity_token(
            wrong_audience_token,
            audience="synvexai.remind",
            expected_nonce_hash=nonce_hash,
        )
    with app.app_context(), pytest.raises(jwt.InvalidAlgorithmError):
        auth._verify_apple_identity_token(
            weak_algorithm_token,
            audience="synvexai.remind",
            expected_nonce_hash=nonce_hash,
        )


def test_apple_token_rejects_invalid_issuer_time_and_audience_shape(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "_get_apple_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())
        ),
    )
    now = int(time.time())
    nonce_hash = hashlib.sha256(b"server-issued-nonce").hexdigest()

    def encode(**overrides):
        claims = {
            "iss": auth.APPLE_ISSUER,
            "aud": "synvexai.remind",
            "sub": "apple.subject.1",
            "iat": now,
            "exp": now + 300,
            "nonce": nonce_hash,
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    invalid_tokens = (
        encode(iss="https://attacker.example"),
        encode(iat=now - 120, exp=now - 60),
        encode(iat=now + 120, exp=now + 300),
        encode(exp=now + auth.APPLE_TOKEN_MAX_AGE_SECONDS + 1),
        encode(aud=["synvexai.remind"]),
    )
    for identity_token in invalid_tokens:
        with app.app_context(), pytest.raises(jwt.PyJWTError):
            auth._verify_apple_identity_token(
                identity_token,
                audience="synvexai.remind",
                expected_nonce_hash=nonce_hash,
            )


def test_apple_code_exchange_never_follows_redirects(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id_token": "header.payload.signature"}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(auth.requests, "post", post)
    token = auth._exchange_apple_authorization_code(
        "single-use-code",
        client_id="com.example.remind.web",
        redirect_uri="https://chat.example.com/login/apple/callback",
        configured_secret="configured-client-secret",
        team_id="",
        key_id="",
        private_key="",
        private_key_path="",
    )

    assert token == "header.payload.signature"
    assert captured["url"] == auth.APPLE_TOKEN_URL
    assert captured["timeout"] == 10
    assert captured["allow_redirects"] is False


def test_new_apple_account_requires_verified_email(app):
    now = int(time.time())
    claims = {
        "sub": "apple.subject.without.email",
        "iat": now,
        "exp": now + 300,
    }
    with app.app_context(), pytest.raises(auth.AppleAuthError, match="apple_email_required"):
        auth._find_or_create_apple_user(claims)
