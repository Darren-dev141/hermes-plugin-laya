# hermes-plugin-laya

Laya decision tools for [Hermes Agent](https://github.com/NousResearch/hermes-agent),
as native tools — Hermes calls Laya directly instead of shelling out to a CLI.

[Laya](https://github.com/Convai-Innovations/laya) is a fast, local,
on-device decision engine: give it a situation and a small set of options
and it returns a pick with calibrated probabilities, in about a second,
with every call written to an auditable decision log. This plugin is the
Hermes face of that server. ("Jev" means Laya here — these are Laya's
tools, served by the Laya running on your machine.)

## The tools

| Tool | What it does |
|---|---|
| `laya_health` | Is the Laya server up and warm? |
| `laya_choose` | Pick the best of ≤10 options for a situation. Options are `{name: definition}` or a bare list of names. |
| `laya_yes_no` | One yes/no question about a situation; returns `p_yes` (0.5 is the yes/no threshold). |
| `laya_rank` | Rank ≤10 candidate strings best-first. |
| `laya_judge` | One choice **plus** typed fields in a single pass: `yes_no` fields return P(yes); `score` fields require `levels` (2+ ordered labels) and return the expected level **index** as a float. Optional `escalate_below` marks low-confidence picks `status: "escalated"` instead of presenting them as settled. |

Every decision result carries its **`decision_id`** — the id under which
Laya logged the call in `logs/decisions.jsonl`. Outcomes can be recorded
against that id (accepted / rejected / fallback / stale / error /
escalated), which is what makes the decision log a calibration record
instead of a pile of guesses.

## Decision semantics (read this before trusting a number)

- **Confidence is a ranking signal, never a gate.** It orders options; it
  is not the probability that the pick is right, and no threshold on it
  should silently allow or block an action. If a judgment matters, that
  discipline lives in your workflow, not in the number.
- **Choice sets are capped at 10 options** — enforced client-side by this
  plugin before any call is made (the server enforces it too). Beyond 10,
  confidence is uncalibrated. Narrow the set first.
- **Definitions are the decision surface.** Laya judges the definitions
  you write for each option, so write each option as the thing itself,
  not a label for it.
- **Score values are expected level indexes**, e.g. `1.5` over levels
  `["low", "medium", "high"]` sits between medium and high. The plugin
  echoes each score field's `levels` next to its value so the index is
  interpretable.
- **Escalation is surfaced, never hidden.** With `escalate_below` set, a
  judge pick under the band comes back `status: "escalated"` with a note:
  it must not be acted on automatically — a human or a stronger judge
  decides explicitly. The call is logged either way.
- **Fail-soft.** If Laya is down, slow, or erroring, the tools return a
  clear `{"error": ...}` result. They never raise into Hermes.

## Install

You need a running Laya server first (loopback, no auth — see the
security note below). Then:

```bash
hermes plugins install Darren-dev141/hermes-plugin-laya
hermes plugins enable hermes-plugin-laya
```

Or manually: clone this repo into `~/.hermes/plugins/hermes-plugin-laya`
and add `hermes-plugin-laya` to `plugins.enabled` in
`~/.hermes/config.yaml`.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Server URL | `LAYA_URL` env var, else plugin setting `url` | `http://127.0.0.1:8765` |
| Timeout (seconds) | `LAYA_TIMEOUT` env var, else plugin setting `timeout_seconds` | `30` |

Plugin settings live under `plugins.entries.hermes-plugin-laya.settings`
in `config.yaml` (and render as a form in the Desktop app's plugin
settings). The environment variables win, matching the convention of
Laya's own client and MCP face.

## Security: Laya stays local

Laya's server has **no authentication by design** — it is built to be
reached only from the machine it runs on. Therefore:

- **Never expose Laya** on a public interface, never port-forward it,
  never put it behind a public tunnel or reverse proxy.
- On any machine this plugin runs on, Laya must be running **on that same
  machine** (loopback) or reachable only over a **private tailnet** —
  point `LAYA_URL` accordingly and nothing wider.
- Anyone who can reach Laya's port can ask it questions and read its
  decision log. Treat reachability as trust.

## Development

Stdlib only — no dependencies to install, for the plugin or its tests:

```bash
python3 -m unittest discover -s tests -v
hermes plugins doctor . --ci
```

The tests run the handlers against a stub Laya server and prove, among
other things, that oversized choice sets and invalid judge schemas are
rejected client-side without a single request reaching the server.

## License

MIT — see [LICENSE](LICENSE).
