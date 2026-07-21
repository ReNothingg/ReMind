import ipaddress
import socket
from typing import Optional, Tuple, cast
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import USER_AGENT
from utils.responses import logger


def build_http_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=0.4,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=50, pool_maxsize=50)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ru,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


HTTP_SESSION = build_http_session()


def _url_origin_for_logging(raw_url: str) -> str:
    """Keep credentials, paths, and query parameters out of application logs."""
    try:
        parsed = urlparse(raw_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "[redacted-url]"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    except (TypeError, ValueError):
        return "[redacted-url]"


def is_safe_url(url: str) -> Tuple[bool, Optional[str]]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, None
        if parsed.username or parsed.password:
            return False, None
        hostname = parsed.hostname
        if not hostname:
            return False, None

        try:
            addr_info = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
            if not addr_info:
                return False, None

            resolved_addresses = {cast(str, info[4][0]) for info in addr_info if info and info[4]}
            if not resolved_addresses:
                return False, None

            for ip_str in resolved_addresses:
                ip_obj = ipaddress.ip_address(ip_str)

                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_multicast
                    or ip_obj.is_reserved
                    or ip_obj.is_unspecified
                ):
                    logger.warning(f"SSRF blocked: {hostname} resolves to {ip_str}")
                    return False, None

            return True, sorted(resolved_addresses)[0]
        except socket.gaierror:
            logger.warning(f"DNS resolution failed for: {hostname}")
            return False, None
    except Exception as exc:
        logger.error("SSRF check failed (%s)", type(exc).__name__)
        return False, None


def make_safe_http_request(
    url: str, method: str = "GET", timeout: int = 10, max_redirects: int = 3, **kwargs
) -> Optional[requests.Response]:
    allow_redirects = bool(kwargs.pop("allow_redirects", True))
    base_headers = dict(kwargs.pop("headers", {}) or {})
    current_url = url

    for _redirect_count in range(max_redirects + 1):
        is_safe, resolved_ip = is_safe_url(current_url)
        if not is_safe:
            logger.warning("Unsafe URL blocked: %s", _url_origin_for_logging(current_url))
            return None

        try:
            parsed = urlparse(current_url)
            hostname = parsed.hostname
            if hostname is None or resolved_ip is None:
                return None

            netloc = resolved_ip
            if ":" in resolved_ip and not resolved_ip.startswith("["):
                netloc = f"[{resolved_ip}]"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            safe_url = urlunparse(parsed._replace(netloc=netloc))

            headers = dict(base_headers)
            headers["Host"] = parsed.netloc

            response = HTTP_SESSION.request(
                method,
                safe_url,
                timeout=timeout,
                headers=headers,
                allow_redirects=False,
                **kwargs,
            )
            if not allow_redirects or not response.is_redirect:
                return response

            location = response.headers.get("Location")
            response.close()
            if not location:
                return None

            current_url = urljoin(current_url, location)
        except Exception as exc:
            logger.error("HTTP request failed (%s)", type(exc).__name__)
            return None

    logger.warning("Too many redirects blocked for URL: %s", _url_origin_for_logging(url))
    return None
