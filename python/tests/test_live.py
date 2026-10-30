"""Live smoke test against https://iriscan.app/api, on the free launch-tool scan only and without
an API key. Skipped unless IRIS_LIVE=1:  IRIS_LIVE=1 python -m unittest tests.test_live -v"""

import json
import os
import unittest

from iris_guard import Guard

# A serial launcher: no launch-tool evidence, a dozen tokens launched.
SERIAL_LAUNCHER = "2zy2NEyvzXfPkdFesbisZViTyz6oCWERFEvSD9PfoRg1"


@unittest.skipUnless(os.environ.get("IRIS_LIVE") == "1", "set IRIS_LIVE=1 to run")
class Live(unittest.TestCase):
    def test_free_mode_without_key(self):
        with Guard("", mode="free", timeout=60, base_url=os.environ.get("IRIS_BASE_URL") or None) as guard:
            r = guard.check(SERIAL_LAUNCHER)
        s = r.summary
        print(json.dumps({"allow": r.allow, "reasons": r.reasons, "warnings": r.warnings, "latency_ms": r.latency_ms, "error": r.error,
                          "verdict": s and s.launch_tool_verdict, "creator_launches": s and s.creator_launches}))
        self.assertIsNone(r.error, f"Iris answered with an error: {r.error and r.error['message']}")
        self.assertEqual(s.launch_tool_verdict, "none")
        self.assertGreaterEqual(s.creator_launches or 0, 1)


if __name__ == "__main__":
    unittest.main()
