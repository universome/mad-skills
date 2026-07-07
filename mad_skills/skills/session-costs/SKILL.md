---
name: session-costs
description: >-
  Token and dollar-cost accounting across past Claude Code sessions. Use when
  the user asks how many tokens they've used, how much their sessions cost, what
  their Claude Code spend is, which session/project/model was most expensive, or
  wants a usage/cost breakdown or report of prior sessions.
---

# session-costs — token & cost accounting for Claude Code

Claude Code records every session as a JSONL transcript under
`~/.claude/projects/<project>/<session-id>.jsonl`, and each assistant message
carries its model and token usage. The bundled `session-costs` CLI parses all of
them, sums tokens per session / project / model, and prices them.

## Usage

```bash
session-costs                 # per-session table + grand total (default)
session-costs --by project    # group by project directory
session-costs --by model      # group by model
session-costs --json          # machine-readable (parse this if summarizing)
```

Report columns: message count, input, output, cache-read, and cache-write
tokens, plus USD cost. A `TOTAL` row and grand totals (tokens, cost, session
count) follow.

## Guidance for Claude

- To answer a specific question ("what did I spend this week?", "most expensive
  session?"), run `session-costs --json` and compute from the structured data
  rather than scraping the table.
- Cache-read tokens usually dominate the token count but are cheap (0.1x input);
  don't be alarmed by a huge token total — the **cost** column is what matters.
- Pick `--by`: session (default), `project`, or `model`, based on what's asked.
- If the output lists `* UNPRICED models`, some model had no entry in the price
  table and its cost was **excluded** — tell the user, and offer to add a price
  via `--prices` (see below).

## Pricing is editable data

Built-in prices (USD per million tokens) use the standard cache multipliers
(5-min write = 1.25x input, 1-hr write = 2x input, cache read = 0.1x input).
**Base rates change — treat totals as estimates** and verify at
<https://www.anthropic.com/pricing>.

Override or add models with a JSON file:

```json
{
  "_families": {
    "opus":   {"input": 15, "output": 75, "cache_read": 1.5,
               "cache_write_5m": 18.75, "cache_write_1h": 30}
  },
  "claude-some-new-model": {"input": 2, "output": 10, "cache_read": 0.2,
                            "cache_write_5m": 2.5, "cache_write_1h": 4}
}
```

```bash
session-costs --prices my-prices.json
```

## Options

```
session-costs [--by session|project|model] [--json]
              [--prices FILE] [--projects-dir DIR]
```

`--projects-dir` (or `CLAUDE_PROJECTS_DIR`) points at a non-default transcripts
root. Requests are de-duplicated by request id, so resumed/forked sessions that
copy history are not double-counted.
