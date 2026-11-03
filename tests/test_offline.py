import os
import socket
import urllib.request

import pytest
import requests

from isoresearch.core import offline
from isoresearch.llm.ollama_client import LLMUnavailable, OllamaClient
from mock_ollama import MockOllama


@pytest.fixture()
def guard():
    offline.enable()
    offline.blocked_attempts.clear()
    yield
    offline.disable()


def test_blocks_external_ip_connections(guard):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(offline.OfflineViolation):
        s.connect(("93.184.216.34", 80))
    s.close()
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 443), timeout=2)
    assert "93.184.216.34" in offline.blocked_attempts


def test_blocks_dns_and_http_libraries(guard):
    with pytest.raises(offline.OfflineViolation):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("https://huggingface.co", timeout=3)
    with pytest.raises(Exception):
        urllib.request.urlopen("http://example.org", timeout=3)
    assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_proxy_environment_is_neutralised(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    offline.enable()
    try:
        assert "HTTPS_PROXY" not in os.environ and os.environ["NO_PROXY"] == "*"
    finally:
        offline.disable()
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:3128"


def test_loopback_is_allowed(guard):
    with MockOllama() as mo:
        c = OllamaClient(mo.url, "mock")
        assert c.is_running()
        assert c.chat([{"role": "user", "content": "x"}]).strip()
    with MockOllama() as mo:
        c = OllamaClient(mo.url.replace("127.0.0.1", "localhost"), "mock")
        assert c.is_running()


def test_ollama_client_refuses_non_local_url_in_strict_mode(guard):
    c = OllamaClient("http://192.168.1.50:11434", "m", require_loopback=lambda: True)
    with pytest.raises(LLMUnavailable, match="loopback"):
        c.list_models()
    assert c.status()["ready"] is False


def test_is_loopback_helpers():
    assert offline.is_loopback_url("http://127.0.0.1:11434")
    assert offline.is_loopback_url("http://localhost:11434")
    assert offline.is_loopback_url("http://[::1]:11434")
    assert not offline.is_loopback_url("http://10.0.0.2:11434")
    assert not offline.is_loopback_url("https://ollama.com")


def test_app_context_enables_guard_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ISORESEARCH_HOME", str(tmp_path / "h"))
    from isoresearch.context import AppContext

    ctx = AppContext.create(enforce_offline=True)
    try:
        assert offline.is_enabled()
        with pytest.raises(OSError):
            socket.create_connection(("8.8.8.8", 53), timeout=2)
    finally:
        ctx.close()
        offline.disable()


def test_no_telemetry_or_remote_assets_in_source():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "isoresearch"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    for bad in ("fonts.googleapis", "google-analytics", "sentry_sdk", "mixpanel", "segment.io", "posthog",
                "cdn.jsdelivr", "unpkg.com", "QWebEngine"):
        assert bad not in text, bad
    assert "0.0.0.0" not in text  # never binds a network server


def test_ai_code_is_never_executed():
    from pathlib import Path

    import re

    root = Path(__file__).resolve().parents[1] / "isoresearch"
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        # builtin exec/eval (Qt's widget.exec() methods are fine), runpy or subprocess are never used
        assert not re.search(r"(?<![\w.])(exec|eval)\(", src), p
        assert "import subprocess" not in src and "runpy" not in src, p
