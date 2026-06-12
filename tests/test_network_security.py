import socket

from utils import network


def test_is_safe_url_rejects_userinfo_without_dns_lookup(monkeypatch):
    def fail_getaddrinfo(*_args, **_kwargs):
        raise AssertionError("userinfo URLs should be rejected before DNS lookup")

    monkeypatch.setattr(network.socket, "getaddrinfo", fail_getaddrinfo)

    assert network.is_safe_url("https://user:pass@example.com/path") == (False, None)


def test_is_safe_url_rejects_hosts_with_any_private_dns_answer(monkeypatch):
    def fake_getaddrinfo(_host, _port, type):
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)

    assert network.is_safe_url("https://mixed.example/path") == (False, None)
