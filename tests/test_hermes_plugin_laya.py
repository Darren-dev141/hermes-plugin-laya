"""Tests for hermes-plugin-laya — stdlib unittest, stub Laya server.

Run:  python3 -m unittest discover -s tests -v
(from the plugin repo root; no third-party packages needed)

The stub implements the same response shapes as the real Laya server
(~/workspace/laya/server.py) and records every request, so tests can prove
client-side validation rejects bad calls BEFORE anything is sent.
"""

import importlib
import json
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_plugin_package():
    """Load the plugin dir as a package despite its hyphenated name
    (Hermes's own loader does the equivalent via its plugin machinery)."""
    name = "hermes_plugin_laya"
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules[name] = pkg
    importlib.import_module(name + ".tools")
    importlib.import_module(name + ".schemas")
    # __init__ needs the package context; load it as part of the package:
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plugin = _load_plugin_package()
tools = sys.modules["hermes_plugin_laya.tools"]


class StubLaya(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        StubLaya.requests.append(("GET", self.path, None))
        if self.path == "/health":
            self._send({"status": "ok", "model": "english", "warm": True})
        else:
            self._send({"detail": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        StubLaya.requests.append(("POST", self.path, payload))
        if self.path == "/choose":
            top = sorted(payload["options"])[0]
            self._send({"choice": top, "confidence": 0.42,
                        "probabilities": {k: 0.1 for k in payload["options"]},
                        "decision_id": "stubchoose01"})
        elif self.path == "/yesno":
            self._send({"p_yes": 0.83, "confidence": 0.83,
                        "decision_id": "stubyesno001"})
        elif self.path == "/rank":
            ranked = [[o, 1.0 - 0.1 * i] for i, o in enumerate(payload["options"])]
            self._send({"best": payload["options"][0], "ranking": ranked,
                        "confidence": 0.5, "decision_id": "stubrank0001"})
        elif self.path == "/judge":
            fields = {}
            for f in payload["schema"].get("fields", []):
                if f["type"] == "yes_no":
                    fields[f["name"]] = {"value": 0.7, "confidence": 0.7}
                else:
                    fields[f["name"]] = {"value": 1.5, "confidence": 0.6}
            self._send({"choice": sorted(payload["options"])[0],
                        "confidence": 0.42,
                        "probabilities": {k: 0.1 for k in payload["options"]},
                        "fields": fields,
                        "schema": {"name": payload["schema"].get("name", "unnamed"),
                                   "version": payload["schema"].get("version", 1)},
                        "decision_id": "stubjudge001"})
        else:
            self._send({"detail": "not found"}, 404)


class PluginTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StubLaya)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = tools.LayaClient("http://127.0.0.1:%d" % cls.port, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        StubLaya.requests = []

    def posts(self):
        return [r for r in StubLaya.requests if r[0] == "POST"]


class TestHandlers(PluginTestCase):
    def test_health(self):
        out = json.loads(tools.make_health(self.client)({}))
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["warm"])

    def test_choose_passthrough_decision_id(self):
        out = json.loads(tools.make_choose(self.client)(
            {"state": "s", "options": {"a": "the a thing", "b": "the b thing"}}))
        self.assertEqual(out["decision_id"], "stubchoose01")
        self.assertEqual(out["choice"], "a")
        payload = self.posts()[0][2]
        self.assertEqual(payload["options"], {"a": "the a thing", "b": "the b thing"})

    def test_choose_list_options_normalized(self):
        tools.make_choose(self.client)({"state": "s", "options": ["x", "y"]})
        payload = self.posts()[0][2]
        self.assertEqual(payload["options"], {"x": "x", "y": "y"})

    def test_choose_more_than_10_rejected_client_side(self):
        opts = {"opt%d" % i: "definition %d" % i for i in range(11)}
        out = json.loads(tools.make_choose(self.client)({"state": "s", "options": opts}))
        self.assertIn("error", out)
        self.assertIn("10", out["error"])
        self.assertEqual(self.posts(), [], "oversized call must never reach the server")

    def test_choose_empty_state_rejected(self):
        out = json.loads(tools.make_choose(self.client)(
            {"state": "  ", "options": {"a": "a"}}))
        self.assertIn("error", out)
        self.assertEqual(self.posts(), [])

    def test_yes_no(self):
        out = json.loads(tools.make_yes_no(self.client)(
            {"state": "inbox has 3 recruiter mails", "question": "Is any urgent?"}))
        self.assertEqual(out["p_yes"], 0.83)
        self.assertEqual(out["decision_id"], "stubyesno001")

    def test_rank(self):
        out = json.loads(tools.make_rank(self.client)(
            {"state": "s", "options": ["q1", "q2", "q3"]}))
        self.assertEqual(out["best"], "q1")
        self.assertEqual(out["decision_id"], "stubrank0001")

    def test_rank_more_than_10_rejected_client_side(self):
        out = json.loads(tools.make_rank(self.client)(
            {"state": "s", "options": ["c%d" % i for i in range(11)]}))
        self.assertIn("error", out)
        self.assertEqual(self.posts(), [])

    def test_judge_happy_path_and_levels_echo(self):
        schema = {"name": "triage", "version": 1, "fields": [
            {"name": "urgent", "type": "yes_no", "question": "Is it urgent?"},
            {"name": "severity", "type": "score",
             "levels": ["low", "medium", "high"]},
        ]}
        out = json.loads(tools.make_judge(self.client)(
            {"state": "s", "options": {"a": "a thing"}, "schema": schema}))
        self.assertEqual(out["decision_id"], "stubjudge001")
        self.assertEqual(out["fields"]["urgent"]["value"], 0.7)
        self.assertEqual(out["fields"]["severity"]["value"], 1.5)
        self.assertEqual(out["fields"]["severity"]["levels"],
                         ["low", "medium", "high"])
        self.assertNotIn("status", out)  # no escalate_below -> faithful passthrough

    def test_judge_score_without_levels_rejected_client_side(self):
        schema = {"name": "triage", "fields": [
            {"name": "severity", "type": "score"}]}
        out = json.loads(tools.make_judge(self.client)(
            {"state": "s", "options": {"a": "a thing"}, "schema": schema}))
        self.assertIn("error", out)
        self.assertIn("severity", out["error"])
        self.assertIn("levels", out["error"])
        self.assertEqual(self.posts(), [], "invalid schema must never reach the server")

    def test_judge_yes_no_without_question_rejected(self):
        schema = {"name": "t", "fields": [{"name": "u", "type": "yes_no"}]}
        out = json.loads(tools.make_judge(self.client)(
            {"state": "s", "options": {"a": "a"}, "schema": schema}))
        self.assertIn("error", out)
        self.assertIn("question", out["error"])
        self.assertEqual(self.posts(), [])

    def test_judge_escalation_marked_not_hidden(self):
        schema = {"name": "triage", "fields": []}
        args = {"state": "s", "options": {"a": "a thing"}, "schema": schema}
        out = json.loads(tools.make_judge(self.client)(
            dict(args, escalate_below=0.9)))  # stub confidence is 0.42
        self.assertEqual(out["status"], "escalated")
        self.assertIn("must not be acted on", out["note"])
        out = json.loads(tools.make_judge(self.client)(
            dict(args, escalate_below=0.3)))
        self.assertEqual(out["status"], "chosen")

    def test_judge_bad_escalate_below_rejected(self):
        out = json.loads(tools.make_judge(self.client)(
            {"state": "s", "options": {"a": "a"},
             "schema": {"name": "t", "fields": []}, "escalate_below": 2}))
        self.assertIn("error", out)
        self.assertEqual(self.posts(), [])


class TestFailSoft(unittest.TestCase):
    def test_laya_down_returns_error_never_raises(self):
        dead = tools.LayaClient("http://127.0.0.1:1", timeout=2)
        for factory, args in [
            (tools.make_health, {}),
            (tools.make_choose, {"state": "s", "options": {"a": "a"}}),
            (tools.make_yes_no, {"state": "s", "question": "q?"}),
            (tools.make_rank, {"state": "s", "options": ["a"]}),
            (tools.make_judge, {"state": "s", "options": {"a": "a"},
                                "schema": {"name": "t", "fields": []}}),
        ]:
            out = json.loads(factory(dead)(args))
            self.assertIn("error", out, factory)
            self.assertIn("unreachable", out["error"])


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.config = {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (toolset, schema, handler)


class TestRegistration(unittest.TestCase):
    def test_register_registers_five_laya_tools(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertEqual(
            sorted(ctx.tools),
            ["laya_choose", "laya_health", "laya_judge", "laya_rank", "laya_yes_no"],
        )
        for name, (toolset, schema, handler) in ctx.tools.items():
            self.assertEqual(toolset, "laya")
            self.assertEqual(schema["name"], name)
            self.assertTrue(callable(handler))


if __name__ == "__main__":
    unittest.main()
