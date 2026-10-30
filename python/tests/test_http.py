"""The guard through the real SDK, against a local server that answers like the Iris API."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from iris_guard import Guard

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures"
MINT = "So11111111111111111111111111111111111111112"
ROUTES = {"/launch-tool": "launch-tool-serial", "/analyze": "analyze-rug", "/insiders": "insiders-linked"}
SEEN: list = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
        SEEN.append({"path": self.path, "auth": self.headers.get("authorization"), "body": body})
        if not self.headers.get("authorization"):
            status, out = 401, json.dumps({"error": "Log in to use Iris, or send an API key", "code": "login"})
        elif self.path in ROUTES:
            status, out = 200, (FIXTURES / f"{ROUTES[self.path]}.json").read_text()
        else:
            status, out = 404, json.dumps({"error": "Not found"})
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *args):
        pass


class ThroughSdk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_full_mode_with_key(self):
        SEEN.clear()
        with Guard("iris_live_test", base_url=self.base_url) as guard:
            r = guard.check(MINT)
        self.assertEqual(r.mode, "full")
        self.assertFalse(r.allow)
        self.assertEqual(len(r.reasons), 4)
        self.assertEqual(sorted(s["path"] for s in SEEN), ["/analyze", "/insiders", "/launch-tool"])
        self.assertTrue(all(s["auth"] == "Bearer iris_live_test" for s in SEEN))
        self.assertEqual(next(s for s in SEEN if s["path"] == "/launch-tool")["body"]["wallet"], MINT)

    def test_fail_closed_without_key(self):
        with Guard("", base_url=self.base_url) as guard:
            r = guard.check(MINT)
        self.assertEqual(r.mode, "free")
        self.assertFalse(r.allow)
        self.assertEqual(r.error["status"], 401)
        self.assertEqual(r.error["code"], "login")


if __name__ == "__main__":
    unittest.main()
