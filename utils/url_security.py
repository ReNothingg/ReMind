from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeUrlError(ValueError):
    pass


BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
}


def _is_blocked_hostname(hostname: str) -> bool:
    normalized = hostname.strip(".").lower()
    return (
        normalized in BLOCKED_HOSTNAMES
        or normalized.endswith(".localhost")
        or normalized.endswith(".local")
    )


def _is_public_global_ip(address: IPAddress) -> bool:
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def _resolve_host_ips(hostname: str, port: int) -> set[IPAddress]:
    try:
        literal_ip = ipaddress.ip_address(hostname)
        return {literal_ip}
    except ValueError:
        pass

    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("URL host could not be resolved") from exc
    except OSError as exc:
        raise UnsafeUrlError("URL host lookup failed") from exc

    addresses: set[IPAddress] = set()
    for record in records:
        sockaddr = record[4]
        if not sockaddr:
            continue
        try:
            addresses.add(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue

    if not addresses:
        raise UnsafeUrlError("URL host did not resolve to an IP address")
    return addresses


def validate_public_http_url(raw_url: str, *, max_length: int = 2048) -> str:
    candidate = (raw_url or "").strip()
    if not candidate:
        raise UnsafeUrlError("URL is required")
    if len(candidate) > max_length:
        raise UnsafeUrlError("URL is too long")
    if any(ord(char) < 32 for char in candidate):
        raise UnsafeUrlError("URL contains control characters")

    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise UnsafeUrlError("Invalid URL") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError("URL scheme is not allowed")
    if not parsed.netloc or not parsed.hostname:
        raise UnsafeUrlError("URL host is required")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL credentials are not allowed")

    hostname = parsed.hostname.strip(".").lower()
    if not hostname or _is_blocked_hostname(hostname):
        raise UnsafeUrlError("URL host is not allowed")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("Invalid URL port") from exc

    addresses = _resolve_host_ips(hostname, port)
    if any(not _is_public_global_ip(address) for address in addresses):
        raise UnsafeUrlError("URL host resolves to a non-public address")

    return candidate
