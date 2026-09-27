"""A stand-in llama-server for supervisor tests: /health, /props, streaming /completion."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok"})
        elif self.path == "/props":
            self._json({"model_alias": "stub.gguf", "model_path": "/x/stub.gguf", "real": True})
        else:
            self._json({"error": "nope"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/completion" and req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ("Hel", "lo"):
                self.wfile.write(
                    f"data: {json.dumps({'content': piece, 'stop': False})}\n\n".encode()
                )
                self.wfile.flush()
            self.wfile.write(b'data: {"content": "", "stop": true}\n\n')
        elif self.path == "/completion":
            self._json({"content": "Hello", "stop": True, "echo": req.get("prompt")})
        else:
            self._json({"error": "nope"}, 404)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    args, _ = ap.parse_known_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
