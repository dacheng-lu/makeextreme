"""The local model adapter: one bounded request, recorded honestly, never retried.

The fake server runs in-process, so these tests need no model, no GPU and no network.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from support import REPO

class _Handler(BaseHTTPRequestHandler):
    reply = {"response": "ok", "thinking": "", "done_reason": "stop",
             "prompt_eval_count": 7, "eval_count": 3, "total_duration": 1}
    delay = 0.0
    tags = {"models": [{"name": "fake:1b", "digest": "sha256:" + "1" * 64}]}

    def do_GET(self):
        body = json.dumps(self.tags).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.delay:
            time.sleep(self.delay)
        body = json.dumps(self.reply).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            pass  # the adapter's timeout closed the socket first: that is the case under test

    def log_message(self, *a):
        pass


class Adapter(unittest.TestCase):
    def serve(self, delay=0.0, reply=None):
        handler = type("H", (_Handler,), {"delay": delay, "reply": reply or _Handler.reply})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def run_adapter(self, base, timeout=5, extra=()):
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="mx-model-")
        self.addCleanup(tmp.cleanup)
        prompt = os.path.join(tmp.name, "prompt.txt")
        out = os.path.join(tmp.name, "reply.json")
        with open(prompt, "w") as f:
            f.write("say ok")
        res = subprocess.run([sys.executable, "-m", "makeextreme.model_runner", "--model", "fake:1b",
                              "--prompt-file", prompt, "--out", out, "--base-url", base,
                              "--timeout", str(timeout), *extra],
                             cwd=REPO, capture_output=True, text=True, timeout=30)
        record = json.load(open(out)) if os.path.exists(out) else None
        return res, record

    def test_one_request_is_recorded_with_the_counters_the_runner_reported(self):
        res, record = self.run_adapter(self.serve())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["response"], "ok")
        self.assertEqual(record["tokens"], {"prompt": 7, "eval": 3})
        self.assertEqual(record["options"]["temperature"], 0.0)
        self.assertEqual(record["model_digest"], "sha256:" + "1" * 64)
        self.assertEqual(record["prompt_sha256"], __import__("hashlib").sha256(b"say ok").hexdigest())

    def test_a_slow_runner_yields_a_timeout_record_not_a_hang(self):
        started = time.monotonic()
        res, record = self.run_adapter(self.serve(delay=3), timeout=0.5)
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertEqual(record["status"], "timeout")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertIsNone(record["response"])

    def test_a_non_loopback_endpoint_is_refused_without_the_explicit_flag(self):
        res, _ = self.run_adapter("http://192.0.2.1:11434")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("non-loopback", res.stderr)


if __name__ == "__main__":
    unittest.main()
