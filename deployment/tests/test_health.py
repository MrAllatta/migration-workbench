"""Tests for ``deployment.health`` module."""

from __future__ import annotations

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class _HealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class _UnhealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(503)
        self.end_headers()
        self.wfile.write(b"unhealthy")

    def log_message(self, format, *args):
        pass


def _start_server(handler_class, port: int):
    server = HTTPServer(("127.0.0.1", port), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def test_wait_for_healthy_returns_true():
    from deployment.health import wait_for_healthy

    server = _start_server(_HealthyHandler, 18765)
    try:
        result = wait_for_healthy("http://127.0.0.1:18765/healthz", timeout=5, interval=0.1)
        assert result is True
    finally:
        server.shutdown()


def test_wait_for_healthy_returns_false_on_timeout():
    from deployment.health import wait_for_healthy

    server = _start_server(_UnhealthyHandler, 18766)
    try:
        result = wait_for_healthy("http://127.0.0.1:18766/healthz", timeout=0.5, interval=0.1)
        assert result is False
    finally:
        server.shutdown()


def test_wait_for_healthy_returns_false_on_connection_error():
    from deployment.health import wait_for_healthy

    result = wait_for_healthy("http://127.0.0.1:18767/healthz", timeout=0.5, interval=0.1)
    assert result is False