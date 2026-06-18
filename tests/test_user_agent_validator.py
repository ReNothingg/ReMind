from config import ALLOWED_USER_AGENT_PATTERNS, BYPASS_USER_AGENT_VALIDATION_ROUTES
from utils.user_agent_validator import UserAgentValidator


def test_user_agent_validator_allows_apple_webkit_networking_subrequests():
    validator = UserAgentValidator(
        allowed_patterns=ALLOWED_USER_AGENT_PATTERNS,
        bypass_routes=[],
        enabled=True,
    )

    assert validator.is_valid_user_agent(
        "com.apple.WebKit.Networking/21624.2.5.11.4 Network/5812.121.1 macOS/26.5.1"
    )


def test_user_agent_validator_bypasses_yandex_verification_file():
    validator = UserAgentValidator(
        allowed_patterns=ALLOWED_USER_AGENT_PATTERNS,
        bypass_routes=BYPASS_USER_AGENT_VALIDATION_ROUTES,
        enabled=True,
    )

    assert validator.should_bypass_validation("/yandex_34c67fdadc366239.html")
    assert not validator.should_bypass_validation("/prefix/yandex_34c67fdadc366239.html")
