"""A tiny fake Ollama HTTP server for tests (binds to 127.0.0.1 only).

It mimics /api/version, /api/tags and streaming /api/chat.  The scripted reply
can reference sources to exercise citation validation.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockOllama:
    def __init__(self, reply: str = "Heavy rain is depleted [S1]. Invented claim [S9].", models=("mock:latest",),
                 delay: float = 0.0):
        self.reply = reply
        self.models = list(models)
        self.delay = delay
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._json({"version": "0.0-mock"})
                if self.path == "/api/tags":
                    return self._json({"models": [{"name": m, "size": 123, "details": {"parameter_size": "1B"}}
                                                  for m in outer.models]})
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append(payload)
                if self.path != "/api/chat":
                    return self._json({"error": "not found"}, 404)
                if payload.get("model") not in outer.models and f"{payload.get('model')}:latest" not in outer.models:
                    return self._json({"error": "model not found"}, 404)
                reply = outer.reply(payload) if callable(outer.reply) else outer.reply
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                try:
                    for word in reply.split(" "):
                        self.wfile.write((json.dumps({"message": {"content": word + " "}, "done": False}) + "\n").encode())
                        self.wfile.flush()
                        if outer.delay:
                            time.sleep(outer.delay)
                    self.wfile.write((json.dumps({"done": True}) + "\n").encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
