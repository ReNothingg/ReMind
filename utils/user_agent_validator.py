import re
import logging
from typing import Dict, List, Optional, Tuple
from flask import request

logger = logging.getLogger(__name__)


class UserAgentValidator:


    def __init__(
        self,
        allowed_patterns: List[str],
        bypass_routes: List[str],
        enabled: bool = True,
    ):

        self.allowed_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in allowed_patterns
        ]
        self.bypass_routes = [
            re.compile(pattern, re.IGNORECASE) for pattern in bypass_routes
        ]
        self.enabled = enabled

    def should_bypass_validation(self, path: str) -> bool:
        for bypass_pattern in self.bypass_routes:
            if bypass_pattern.search(path):
                logger.debug(f"User-Agent validation bypassed for path: {path}")
                return True
        return False

    def is_valid_user_agent(self, user_agent: Optional[str]) -> bool:
        if not self.enabled:
            return True

        if not user_agent:
            logger.warning("Request with missing User-Agent header")
            return False
        for pattern in self.allowed_patterns:
            if pattern.search(user_agent):
                logger.debug(f"User-Agent validation passed: {user_agent[:50]}...")
                return True

        logger.warning(f"Invalid/Custom User-Agent detected: {user_agent}")
        return False

    def validate_request(self) -> Tuple[bool, Optional[str]]:
        if not self.enabled:
            return True, None

        path = request.path
        if self.should_bypass_validation(path):
            return True, None

        user_agent = request.headers.get("User-Agent")

        if not self.is_valid_user_agent(user_agent):
            error_msg = (
                "Access denied: Custom or invalid User-Agent detected. "
                "Please use a standard browser."
            )
            logger.warning(
                f"User-Agent validation failed for {request.remote_addr} "
                f"on {path} with User-Agent: {user_agent}"
            )
            return False, error_msg

        return True, None


def log_suspicious_user_agent(
    user_agent: Optional[str], ip: str, endpoint: str, additional_info: dict = None
) -> None:
    additional = additional_info or {}

    log_entry = {
        "ip": ip,
        "endpoint": endpoint,
        "user_agent": user_agent if user_agent else "MISSING",
        **additional,
    }

    logger.warning(f"Suspicious User-Agent detected: {log_entry}")


def get_common_user_agents() -> Dict[str, str]:
    return {
        "Chrome": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Firefox": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
            "Gecko/20100101 Firefox/123.0"
        ),
        "Safari": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Version/17.2.1 Safari/537.36"
        ),
        "Edge": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        ),
        "Opera": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/110.0.0.0"
        ),
    }
