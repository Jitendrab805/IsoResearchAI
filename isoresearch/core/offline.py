"""Offline enforcement.

When strict offline mode is on, every *application-initiated* outbound socket
connection to a non-loopback address is refused inside this Python process.
This covers ``requests``, ``urllib``, ``http.client``, Hugging Face downloads,
and anything else built on the standard ``socket`` module.

Loopback (127.0.0.0/8, ::1, ``localhost``) stays allowed so the app can talk to
the local Ollama service.  The guard cannot control *other* programs (for
example the Ollama daemon itself, which runs as its own process) — that is
explained in the Settings → Privacy panel.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class OfflineViolation(ConnectionRefusedError):
    """Raised when strict offline mode blocks an outbound connection."""


_lock = threading.Lock()
_enabled = False
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection
blocked_attempts: list[str] = []

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


def is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    h = str(host).strip("[]").lower()
    if h in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    try:
        return is_loopback_host(urlparse(url).hostname)
    except Exception:  # noqa: BLE001
        return False


def _check(address) -> None:
    if not _enabled:
        return
    # AF_UNIX sockets (str/bytes paths) are local by definition.
    if isinstance(address, (str, bytes)):
        return
    host = address[0] if isinstance(address, tuple) and address else None
    if not is_loopback_host(host):
        msg = f"Strict offline mode blocked a connection to {host!r}"
        blocked_attempts.append(str(host))
        log.warning(msg)
        raise OfflineViolation(msg)


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(address)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(address)
    return _orig_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    # Refuse DNS lookups of external names too: avoids leaking hostnames to DNS.
    if _enabled and host is not None and not is_loopback_host(host):
        try:
            ipaddress.ip_address(str(host))  # literal IPs are checked at connect()
        except ValueError:
            msg = f"Strict offline mode blocked DNS lookup of {host!r}"
            blocked_attempts.append(str(host))
            log.warning(msg)
            raise OfflineViolation(msg) from None
    return _orig_getaddrinfo(host, *args, **kwargs)


OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "ANONYMIZED_TELEMETRY": "False",
}


PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_saved_proxy_env: dict[str, str] = {}


def enable() -> None:
    global _enabled
    with _lock:
        # A proxy on 127.0.0.1 would otherwise be an escape hatch: loopback is allowed, the proxy is not.
        for k in PROXY_VARS:
            if k in os.environ:
                _saved_proxy_env[k] = os.environ.pop(k)
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
        socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
        for k, v in OFFLINE_ENV.items():
            os.environ[k] = v
        _enabled = True
    log.info("Strict offline mode enabled (loopback only).")


def disable() -> None:
    """Allow outbound connections again (only via the explicit Settings toggle)."""
    global _enabled
    with _lock:
        socket.socket.connect = _orig_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _orig_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]
        os.environ.update(_saved_proxy_env)
        _saved_proxy_env.clear()
        _enabled = False
    log.info("Strict offline mode disabled by user.")


def is_enabled() -> bool:
    return _enabled


def apply(strict: bool) -> None:
    enable() if strict else disable()
