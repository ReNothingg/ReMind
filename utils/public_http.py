from __future__ import annotations

import codecs
import re
import ssl
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import urllib3

from utils.url_security import UnsafeUrlError, _is_public_global_ip, _resolve_host_ips


@contextmanager
def public_http_get(url: str, *, headers: dict, timeout: float, **_kwargs):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(char) < 33 for char in url):
        raise UnsafeUrlError("invalid_public_url")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsafeUrlError("invalid_public_url")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise UnsafeUrlError("public_port_required")
    addresses = _resolve_host_ips(host, port)
    if any(not _is_public_global_ip(address) for address in addresses):
        raise UnsafeUrlError("non_public_address")
    address = str(sorted(addresses, key=str)[0])
    request_timeout = urllib3.Timeout(connect=timeout, read=timeout)
    pool = (
        urllib3.HTTPSConnectionPool(
            address,
            port,
            server_hostname=host,
            assert_hostname=host,
            cert_reqs=ssl.CERT_REQUIRED,
            timeout=request_timeout,
            maxsize=1,
        )
        if parsed.scheme == "https"
        else urllib3.HTTPConnectionPool(address, port, timeout=request_timeout, maxsize=1)
    )
    host_header = f"[{host}]" if ":" in host else host
    if port != (443 if parsed.scheme == "https" else 80):
        host_header += f":{port}"
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    response = None
    try:
        response = pool.urlopen(
            "GET",
            target,
            headers={**headers, "Host": host_header, "Accept-Encoding": "identity"},
            redirect=False,
            retries=False,
            preload_content=False,
        )
        yield _PublicResponse(response, url, time.monotonic() + timeout)
    finally:
        if response is not None:
            response.close()
        pool.close()


class _PublicResponse:
    def __init__(self, response, url: str, deadline: float):
        self.raw = response
        self.url = url
        self.headers = response.headers
        self.status_code = response.status
        self.is_redirect = response.status in {301, 302, 303, 307, 308}
        self.is_permanent_redirect = response.status in {301, 308}
        self.encoding = "utf-8"
        charset = re.search(
            r"charset\s*=\s*[\"']?([a-zA-Z0-9_-]{1,64})", self.headers.get("content-type", ""), re.I
        )
        if charset:
            try:
                codecs.lookup(charset.group(1))
                self.encoding = charset.group(1)
            except LookupError:
                pass
        self.deadline = deadline

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("public_http_error")

    def iter_content(self, chunk_size: int):
        if self.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
            raise ValueError("compressed_response_not_supported")
        for chunk in self.raw.stream(chunk_size, decode_content=False):
            if time.monotonic() > self.deadline:
                raise TimeoutError("public_http_timeout")
            yield chunk
