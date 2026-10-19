"""Tool handlers — Laya over HTTP, stdlib only.

Mirrors the contract of Laya's own client (client.py against the always-warm
server on 127.0.0.1:8765):

  * choice sets are capped at 10 options — enforced HERE, client-side, so an
    oversized call fails with a clear message and never reaches the server
    (the server would 400 it anyway: confidence is uncalibrated beyond 10);
  * score fields in a judge schema REQUIRE `levels` (2+ ordered labels) and
    return the expected level index as a float; yes_no fields return P(yes)
    with 0.5 as the yes/no threshold;
  * confidence is a ranking signal, never a gate — results pass it through
    untouched, and a judge result whose choice confidence falls under the
    caller's `escalate_below` is marked status="escalated" so the caller
    decides explicitly instead of the low-confidence pick being hidden;
  * every decision result carries its `decision_id` from Laya's log.

Fail-soft: any transport or server problem becomes an {"error": ...} JSON
string. Handlers never raise, so a down Laya can never crash Hermes.

Config: the LAYA_URL environment variable wins (the convention across Laya's
own client and MCP face), then the plugin's `url` / `timeout_seconds`
settings, then the loopback default.
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 30
MAX_OPTIONS = 10


class LayaError(Exception):
    """A Laya call problem that becomes an {"error": ...} tool result."""


class LayaClient:
    def __init__(self, base_url=DEFAULT_URL, timeout=DEFAULT_TIMEOUT):
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT

    def _request(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                body = json.loads(e.read())
                detail = body.get("detail") or body.get("error") or ""
            except Exception:
                pass
            raise LayaError(
                "Laya server at %s returned HTTP %d%s"
                % (self.base_url, e.code, (": " + str(detail)) if detail else "")
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LayaError(
                "Laya unreachable at %s (%s). Is the Laya server running? "
                "Start it with laya's start-server.sh on the machine Hermes "
                "runs on — Laya is local-only by design." % (self.base_url, e)
            ) from e
        except (ValueError, KeyError) as e:
            raise LayaError(
                "Unexpected response from Laya at %s: %s" % (self.base_url, e)
            ) from e

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, payload):
        return self._request("POST", path, payload)


# ---------------------------------------------------------------- validation

def _check_state(state):
    if not isinstance(state, str) or not state.strip():
        return "'state' must be a non-empty string describing the situation to judge"
    return None


def _normalize_options(options):
    """Return (options_dict, error). A bare list of names becomes
    {name: name}; a dict of name -> definition passes through."""
    if isinstance(options, (list, tuple)):
        if not options:
            return None, "'options' must not be empty"
        for o in options:
            if not isinstance(o, str) or not o.strip():
                return None, "every option must be a non-empty string, got %r" % (o,)
        options = {o: o for o in options}
    if not isinstance(options, dict) or not options:
        return None, "'options' must be a non-empty object {name: definition} or list of names"
    if len(options) > MAX_OPTIONS:
        return None, (
            "%d options given; Laya choice sets are capped at %d "
            "(confidence is uncalibrated beyond %d). Narrow the set first, "
            "then call again." % (len(options), MAX_OPTIONS, MAX_OPTIONS)
        )
    for name, definition in options.items():
        if not isinstance(name, str) or not name.strip():
            return None, "option names must be non-empty strings, got %r" % (name,)
        if not isinstance(definition, str) or not definition.strip():
            return None, "option %r needs a non-empty definition string" % (name,)
    return options, None


def _validate_judge_schema(schema):
    """Return an error string or None. Client-side mirror of the server's
    rules, with messages that name the offending field."""
    if not isinstance(schema, dict):
        return "'schema' must be an object {name, version?, fields: [...]}"
    if not schema.get("name") or not isinstance(schema.get("name"), str):
        return "'schema.name' is required (a stable name so decision logs stay comparable)"
    fields = schema.get("fields", [])
    if not isinstance(fields, list):
        return "'schema.fields' must be a list"
    seen = set()
    for f in fields:
        if not isinstance(f, dict):
            return "each schema field must be an object, got %r" % (f,)
        fname = f.get("name")
        ftype = f.get("type")
        if not fname or not isinstance(fname, str):
            return "a schema field is missing its 'name': %r" % (f,)
        if fname in seen:
            return "duplicate schema field name %r" % fname
        seen.add(fname)
        if ftype not in ("yes_no", "score"):
            return "field %r: 'type' must be 'yes_no' or 'score', got %r" % (fname, ftype)
        if ftype == "yes_no":
            if not f.get("question") or not isinstance(f.get("question"), str):
                return "field %r: yes_no fields require a 'question'" % fname
        else:
            levels = f.get("levels")
            if not isinstance(levels, (list, tuple)) or len(levels) < 2:
                return (
                    "field %r: score fields REQUIRE 'levels' — 2+ ordered "
                    "labels, worst/lowest first. The returned value is the "
                    "expected level index (a float), not the label." % fname
                )
            for lv in levels:
                if not isinstance(lv, str) or not lv.strip():
                    return "field %r: every level must be a non-empty string, got %r" % (fname, lv)
    return None


def _err(message):
    return json.dumps({"error": message})


# ------------------------------------------------------------------ handlers
# Each factory takes the client and returns a Hermes handler:
# def handler(args: dict, **kwargs) -> str  (always a JSON string, never raises)

def make_health(client):
    def laya_health(args, **kwargs):
        try:
            out = client.get("/health")
            out = dict(out)
            out["url"] = client.base_url
            return json.dumps(out)
        except LayaError as e:
            return _err(str(e))
        except Exception as e:  # handlers never raise into Hermes
            return _err("laya_health failed unexpectedly: %s" % e)

    return laya_health


def make_choose(client):
    def laya_choose(args, **kwargs):
        try:
            err = _check_state(args.get("state"))
            if err:
                return _err(err)
            options, err = _normalize_options(args.get("options"))
            if err:
                return _err(err)
            payload = {"state": args["state"], "options": options}
            if args.get("instructions"):
                payload["instructions"] = args["instructions"]
            return json.dumps(client.post("/choose", payload))
        except LayaError as e:
            return _err(str(e))
        except Exception as e:
            return _err("laya_choose failed unexpectedly: %s" % e)

    return laya_choose


def make_yes_no(client):
    def laya_yes_no(args, **kwargs):
        try:
            err = _check_state(args.get("state"))
            if err:
                return _err(err)
            question = args.get("question")
            if not isinstance(question, str) or not question.strip():
                return _err("'question' must be a non-empty yes/no question")
            return json.dumps(
                client.post("/yesno", {"state": args["state"], "question": question})
            )
        except LayaError as e:
            return _err(str(e))
        except Exception as e:
            return _err("laya_yes_no failed unexpectedly: %s" % e)

    return laya_yes_no


def make_rank(client):
    def laya_rank(args, **kwargs):
        try:
            err = _check_state(args.get("state"))
            if err:
                return _err(err)
            options = args.get("options")
            if not isinstance(options, (list, tuple)) or not options:
                return _err("'options' must be a non-empty list of candidate strings")
            if len(options) > MAX_OPTIONS:
                return _err(
                    "%d candidates given; Laya ranking is capped at %d. "
                    "Shortlist first, then rank." % (len(options), MAX_OPTIONS)
                )
            for o in options:
                if not isinstance(o, str) or not o.strip():
                    return _err("every candidate must be a non-empty string, got %r" % (o,))
            payload = {"state": args["state"], "options": list(options)}
            if args.get("instructions"):
                payload["instructions"] = args["instructions"]
            return json.dumps(client.post("/rank", payload))
        except LayaError as e:
            return _err(str(e))
        except Exception as e:
            return _err("laya_rank failed unexpectedly: %s" % e)

    return laya_rank


def make_judge(client):
    def laya_judge(args, **kwargs):
        try:
            err = _check_state(args.get("state"))
            if err:
                return _err(err)
            options, err = _normalize_options(args.get("options"))
            if err:
                return _err(err)
            schema = args.get("schema")
            err = _validate_judge_schema(schema)
            if err:
                return _err(err)
            escalate_below = args.get("escalate_below")
            if escalate_below is not None:
                if not isinstance(escalate_below, (int, float)) or isinstance(
                    escalate_below, bool
                ) or not (0 <= float(escalate_below) <= 1):
                    return _err("'escalate_below' must be a number between 0 and 1")
            payload = {"state": args["state"], "options": options, "schema": schema}
            if args.get("instructions"):
                payload["instructions"] = args["instructions"]
            out = dict(client.post("/judge", payload))
            # Echo each score field's levels beside its value so the index is
            # interpretable without re-reading the request.
            levels_by_field = {
                f["name"]: list(f["levels"])
                for f in schema.get("fields", [])
                if isinstance(f, dict) and f.get("type") == "score" and f.get("levels")
            }
            if levels_by_field and isinstance(out.get("fields"), dict):
                for fname, levels in levels_by_field.items():
                    if fname in out["fields"]:
                        out["fields"][fname] = dict(out["fields"][fname])
                        out["fields"][fname]["levels"] = levels
            # Surface the escalation instead of hiding a low-confidence pick.
            if escalate_below is not None:
                confidence = out.get("confidence")
                if isinstance(confidence, (int, float)) and confidence < float(
                    escalate_below
                ):
                    out["status"] = "escalated"
                    out["note"] = (
                        "Choice confidence %.3f is below escalate_below=%.2f: "
                        "this pick is NOT settled and must not be acted on "
                        "automatically. Decide explicitly (human or stronger "
                        "judge); the decision_id above is logged either way, "
                        "and its outcome can be recorded against it."
                        % (confidence, float(escalate_below))
                    )
                else:
                    out["status"] = "chosen"
            return json.dumps(out)
        except LayaError as e:
            return _err(str(e))
        except Exception as e:
            return _err("laya_judge failed unexpectedly: %s" % e)

    return laya_judge


def build_client(ctx=None):
    """Resolve config: LAYA_URL env > plugin settings > loopback default."""
    url = os.environ.get("LAYA_URL") or None
    timeout = None
    get_config = getattr(ctx, "get_config", None) if ctx is not None else None
    if callable(get_config):
        try:
            if url is None:
                url = get_config("url", default=None)
            timeout = get_config("timeout_seconds", default=None)
        except Exception:
            pass  # settings are an optimization; defaults below still work
    env_timeout = os.environ.get("LAYA_TIMEOUT")
    if env_timeout:
        try:
            timeout = int(env_timeout)
        except ValueError:
            pass
    return LayaClient(base_url=url or DEFAULT_URL, timeout=timeout or DEFAULT_TIMEOUT)
