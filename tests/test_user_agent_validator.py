from config import ALLOWED_USER_AGENT_PATTERNS
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
