import socket
import ipaddress
import requests
from typing import Optional, Tuple
from urllib.parse import urlparse
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

def is_safe_url(url: str) -> Tuple[bool, Optional[str]]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, None
        hostname = parsed.hostname
        if not hostname:
            return False, None

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            if not addr_info:
                return False, None

            ip_str = addr_info[0][4][0]
            ip_obj = ipaddress.ip_address(ip_str)

            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
            ):
                logger.warning(f"SSRF blocked: {hostname} resolves to {ip_str}")
                return False, None

            return True, ip_str
        except socket.gaierror:
            logger.warning(f"DNS resolution failed for: {hostname}")
            return False, None
    except Exception as e:
        logger.error(f"SSRF Check Error: {e}")
        return False, None

def make_safe_http_request(
    url: str, method: str = "GET", timeout: int = 10, **kwargs
) -> Optional[requests.Response]:
    is_safe, resolved_ip = is_safe_url(url)
    if not is_safe:
        logger.warning(f"Unsafe URL blocked: {url}")
        return None

    try:
        parsed = urlparse(url)
        safe_url = url.replace(parsed.hostname, resolved_ip)

        headers = kwargs.pop("headers", {})
        headers["Host"] = parsed.hostname

        response = HTTP_SESSION.request(
            method, safe_url, timeout=timeout, headers=headers, **kwargs
        )
        return response
    except Exception as e:
        logger.error(f"HTTP request error: {e}")
        return None