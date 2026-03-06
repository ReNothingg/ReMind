import utils.brute_force as brute_force_module


def _clear_bruteforce_state():
    brute_force_module._attempt_store.clear()
    brute_force_module._lockout_store.clear()


def setup_function():
    _clear_bruteforce_state()


def teardown_function():
    _clear_bruteforce_state()


def test_get_identifier_uses_ip_email_and_combined_hashes(app):
    protection = brute_force_module.BruteForceProtection(use_redis=False)

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.10"}):
        assert protection._get_identifier("ip") == "bf:ip:203.0.113.10"
        assert protection._get_identifier("email", "User@Example.com").startswith("bf:email:")
        combined = protection._get_identifier("combined", "User@Example.com")
        assert combined.startswith("bf:combined:")
        assert combined.count(":") == 3


def test_record_attempt_and_lockout_in_memory(app):
    protection = brute_force_module.BruteForceProtection(
        max_attempts=2,
        lockout_duration=30,
        use_redis=False,
        progressive=False,
    )

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "198.51.100.5"}):
        is_locked, remaining = protection.record_attempt("email", "user@example.com", success=False)
        assert is_locked is False
        assert remaining == 1

        is_locked, remaining = protection.record_attempt("email", "user@example.com", success=False)
        assert is_locked is True
        assert remaining == 0

        locked, seconds = protection.is_locked("email", "user@example.com")
        assert locked is True
        assert seconds > 0


def test_successful_attempt_clears_recorded_attempts(app):
    protection = brute_force_module.BruteForceProtection(max_attempts=3, use_redis=False)

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "198.51.100.6"}):
        protection.record_attempt("email", "user@example.com", success=False)
        identifier = protection._get_identifier("email", "user@example.com")
        assert brute_force_module._attempt_store[identifier]

        is_locked, remaining = protection.record_attempt("email", "user@example.com", success=True)
        assert is_locked is False
        assert remaining == protection.max_attempts
        assert brute_force_module._attempt_store[identifier] == []


def test_progressive_lockout_duration_caps_at_maximum(app):
    protection = brute_force_module.BruteForceProtection(
        lockout_duration=60,
        use_redis=False,
        progressive=True,
    )

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "198.51.100.7"}):
        identifier = protection._get_identifier("email", "user@example.com")
        brute_force_module._lockout_store[f"{identifier}:count"] = 10
        assert (
            protection._get_lockout_duration(identifier) == brute_force_module.MAX_LOCKOUT_DURATION
        )


def test_check_brute_force_returns_429_when_identifier_is_locked(app, monkeypatch):
    class LockedProtection:
        def is_locked(self, *_args, **_kwargs):
            return True, 61

    monkeypatch.setattr(brute_force_module, "brute_force_protection", LockedProtection())

    @brute_force_module.check_brute_force("email")
    def protected():
        return "ok"

    with app.test_request_context(
        "/login",
        method="POST",
        json={"email": "user@example.com"},
        environ_base={"REMOTE_ADDR": "192.0.2.1"},
    ):
        result = protected()

    inner_response, inner_status = result[0]
    assert result[1] == 429
    assert inner_status == 429
    assert inner_response.get_json()["error"]["code"] == "account_locked"


def test_check_brute_force_allows_request_when_not_locked(app, monkeypatch):
    class OpenProtection:
        def is_locked(self, *_args, **_kwargs):
            return False, 0

    monkeypatch.setattr(brute_force_module, "brute_force_protection", OpenProtection())

    @brute_force_module.check_brute_force("combined")
    def protected():
        return "ok"

    with app.test_request_context("/login", method="POST", json={"email": "user@example.com"}):
        assert protected() == "ok"


def test_record_login_attempt_tracks_email_ip_and_combined(monkeypatch):
    calls = []

    class Recorder:
        def record_attempt(self, identifier_type, identifier_value, success):
            calls.append((identifier_type, identifier_value, success))

    monkeypatch.setattr(brute_force_module, "brute_force_protection", Recorder())

    brute_force_module.record_login_attempt("user@example.com", success=False)

    assert calls == [
        ("email", "user@example.com", False),
        ("ip", None, False),
        ("combined", "user@example.com", False),
    ]
