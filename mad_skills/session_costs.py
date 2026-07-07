"""Token & cost accounting across Claude Code sessions.

Claude Code writes every session to a JSONL transcript under
``~/.claude/projects/<project>/<session-id>.jsonl``. Each assistant message
carries ``message.model`` and ``message.usage`` (input / output / cache-read /
cache-creation token counts). This tool sums those per session, project, and
model, and prices them.

Pricing is DATA, not code: built-in defaults live in ``DEFAULT_PRICES`` (USD
per million tokens), and can be fully overridden with ``--prices prices.json``.
Verify current numbers at https://www.anthropic.com/pricing — the defaults use
the standard cache multipliers (5m write = 1.25x input, 1h write = 2x input,
cache read = 0.1x input) but the base rates can change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# USD per 1,000,000 tokens. Override per-model with --prices <file>.
# Keyed by exact model id; unknown ids fall back to family matching (see
# _price_for), and anything still unmatched is reported as UNPRICED.
DEFAULT_PRICES = {
    "_families": {
        "opus":   {"input": 15.0, "output": 75.0, "cache_read": 1.5,
                   "cache_write_5m": 18.75, "cache_write_1h": 30.0},
        "sonnet": {"input": 3.0,  "output": 15.0, "cache_read": 0.3,
                   "cache_write_5m": 3.75,  "cache_write_1h": 6.0},
        "haiku":  {"input": 1.0,  "output": 5.0,  "cache_read": 0.1,
                   "cache_write_5m": 1.25,  "cache_write_1h": 2.0},
    },
    # Exact-id overrides can go here, e.g.:
    # "claude-opus-4-8": {"input": 15.0, "output": 75.0, ...},
}

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
              "cache_write_5m", "cache_write_1h")


def projects_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECTS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude" / "projects"


def _load_prices(path: str | None) -> dict:
    prices = json.loads(json.dumps(DEFAULT_PRICES))  # deep copy
    if path:
        override = json.loads(Path(path).expanduser().read_text())
        # shallow-merge families + exact ids
        for k, v in override.items():
            if k == "_families":
                prices.setdefault("_families", {}).update(v)
            else:
                prices[k] = v
    return prices


def _price_for(model: str, prices: dict) -> dict | None:
    if model in prices:
        return prices[model]
    fams = prices.get("_families", {})
    for fam, rate in fams.items():
        if fam in (model or "").lower():
            return rate
    return None


def _zero_usage() -> dict:
    return {k: 0 for k in USAGE_KEYS}


def _extract_usage(usage: dict) -> dict:
    """Normalize a message.usage blob into our five token buckets."""
    cc = usage.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        # no per-tier breakdown; treat all cache creation as 5-minute writes
        w5 = usage.get("cache_creation_input_tokens", 0) or 0
        w1 = 0
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_write_5m": w5 or 0,
        "cache_write_1h": w1 or 0,
    }


def _cost(tokens: dict, rate: dict) -> float:
    return (
        tokens["input_tokens"] * rate["input"]
        + tokens["output_tokens"] * rate["output"]
        + tokens["cache_read_input_tokens"] * rate["cache_read"]
        + tokens["cache_write_5m"] * rate["cache_write_5m"]
        + tokens["cache_write_1h"] * rate["cache_write_1h"]
    ) / 1_000_000


def scan(prices: dict, root: Path) -> dict:
    """Walk every transcript once, deduping API requests by requestId so a
    resumed/forked session that copies history isn't double-counted."""
    seen_requests: set[str] = set()
    sessions: dict = {}
    unpriced: dict[str, int] = {}

    for jf in sorted(root.rglob("*.jsonl")):
        project = jf.parent.name
        sid = jf.stem
        for line in jf.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if not usage:
                continue
            req = rec.get("requestId") or msg.get("id") or rec.get("uuid")
            if req is not None:
                if req in seen_requests:
                    continue
                seen_requests.add(req)

            model = msg.get("model") or "unknown"
            tok = _extract_usage(usage)

            s = sessions.setdefault(sid, {
                "session": sid, "project": project,
                "cwd": rec.get("cwd", ""),
                "models": {}, "messages": 0,
                "tokens": _zero_usage(), "cost": 0.0, "unpriced": False,
            })
            s["messages"] += 1
            m = s["models"].setdefault(model, {"tokens": _zero_usage(),
                                               "cost": 0.0, "messages": 0})
            m["messages"] += 1
            for k in USAGE_KEYS:
                s["tokens"][k] += tok[k]
                m["tokens"][k] += tok[k]

            rate = _price_for(model, prices)
            if rate is None:
                billable = sum(tok.values())
                if billable > 0:  # ignore synthetic/0-token messages
                    unpriced[model] = unpriced.get(model, 0) + billable
                    s["unpriced"] = True
                continue
            c = _cost(tok, rate)
            s["cost"] += c
            m["cost"] += c

    return {"sessions": sessions, "unpriced": unpriced}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _fmt_tokens(n: int) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n/div:.2f}{unit}"
    return str(n)


def _total_tokens(t: dict) -> int:
    return sum(t[k] for k in USAGE_KEYS)


def _aggregate(sessions: dict, by: str) -> list[dict]:
    if by == "session":
        rows = []
        for s in sessions.values():
            rows.append({"label": s["session"][:8], "project": s["project"],
                         "tokens": s["tokens"], "cost": s["cost"],
                         "messages": s["messages"], "unpriced": s["unpriced"]})
        return rows
    groups: dict = {}
    for s in sessions.values():
        if by == "project":
            keys = [(s["project"], s["tokens"], s["cost"], s["messages"], s["unpriced"])]
        else:  # model
            keys = [(model, mv["tokens"], mv["cost"], mv["messages"], False)
                    for model, mv in s["models"].items()]
        for label, tok, cost, msgs, unp in keys:
            g = groups.setdefault(label, {"label": label, "project": "",
                                          "tokens": _zero_usage(), "cost": 0.0,
                                          "messages": 0, "unpriced": False})
            for k in USAGE_KEYS:
                g["tokens"][k] += tok[k]
            g["cost"] += cost
            g["messages"] += msgs
            g["unpriced"] = g["unpriced"] or unp
    return list(groups.values())


def render(result: dict, by: str) -> str:
    sessions = result["sessions"]
    rows = _aggregate(sessions, by)
    rows.sort(key=lambda r: r["cost"], reverse=True)

    out = []
    head = f"{'':1}{by.upper():<26} {'MSGS':>5} {'IN':>8} {'OUT':>8} " \
           f"{'CACHE-R':>8} {'CACHE-W':>8} {'COST $':>10}"
    out.append(head)
    out.append("-" * len(head))
    tot = _zero_usage()
    tot_cost = 0.0
    tot_msgs = 0
    for r in rows:
        t = r["tokens"]
        cw = t["cache_write_5m"] + t["cache_write_1h"]
        flag = "*" if r["unpriced"] else " "
        out.append(
            f"{flag}{r['label']:<26} {r['messages']:>5} "
            f"{_fmt_tokens(t['input_tokens']):>8} "
            f"{_fmt_tokens(t['output_tokens']):>8} "
            f"{_fmt_tokens(t['cache_read_input_tokens']):>8} "
            f"{_fmt_tokens(cw):>8} {r['cost']:>10.2f}"
        )
        for k in USAGE_KEYS:
            tot[k] += t[k]
        tot_cost += r["cost"]
        tot_msgs += r["messages"]
    out.append("-" * len(head))
    cw = tot["cache_write_5m"] + tot["cache_write_1h"]
    out.append(
        f" {'TOTAL':<26} {tot_msgs:>5} "
        f"{_fmt_tokens(tot['input_tokens']):>8} "
        f"{_fmt_tokens(tot['output_tokens']):>8} "
        f"{_fmt_tokens(tot['cache_read_input_tokens']):>8} "
        f"{_fmt_tokens(cw):>8} {tot_cost:>10.2f}"
    )
    out.append("")
    out.append(f"Total tokens: {_fmt_tokens(_total_tokens(tot))}  |  "
               f"Total cost: ${tot_cost:,.2f}  |  Sessions: {len(sessions)}")

    if result["unpriced"]:
        out.append("")
        out.append("* UNPRICED models (no price in table — cost excluded):")
        for model, toks in sorted(result["unpriced"].items()):
            out.append(f"    {model}: {_fmt_tokens(toks)} tokens")
        out.append("  Add them via --prices <file> to include their cost.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="session-costs",
        description="Token & $ accounting across your Claude Code sessions.",
    )
    p.add_argument("--by", choices=["session", "project", "model"],
                   default="session", help="how to group the report")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--prices", help="JSON file overriding the price table")
    p.add_argument("--projects-dir",
                   help="transcripts root (default ~/.claude/projects)")
    args = p.parse_args(argv)

    root = Path(args.projects_dir).expanduser() if args.projects_dir \
        else projects_dir()
    if not root.exists():
        print(f"No transcripts found at {root}", file=sys.stderr)
        return 1

    prices = _load_prices(args.prices)
    result = scan(prices, root)

    if not result["sessions"]:
        print(f"No assistant messages with usage found under {root}")
        return 0

    if args.json:
        # totals + per-session detail
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render(result, args.by))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
