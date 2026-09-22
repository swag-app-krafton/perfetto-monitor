"""Live token-consumption monitor.

Reads the real `usage` blocks Claude Code writes into its session transcripts
and reports what was actually spent. Nothing here estimates: every number is
server-reported. In particular this module deliberately does NOT report
"tokens saved" -- that would require knowing the cost of the path not taken,
which is a counterfactual and cannot be measured, only modelled. The graphify
`benchmark` command does model it (words*4/3 over chars/4) and its ratio should
not be mistaken for an accounting figure.

Attribution caveat: a tool result's token cost lands on the API call made
*after* the result enters the context, so tool attribution is inferred from
ordering rather than read from a label. It is sound in aggregate and fuzzy for
any single call.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Tool calls grouped by how they put repository content into the context
# window, which is the comparison the dashboard exists to make.
GRAPH_TOOLS = {"graphify"}
READ_TOOLS = {"Read", "NotebookRead"}
SEARCH_TOOLS = {"Grep", "Glob"}

# Bash is a read of the repo only when the command is actually reading it; a
# `git commit` is not context intake. Matching stays deliberately shallow --
# the first tokens of the command line -- because guessing deeper misattributes
# more often than it helps.
_BASH_READ = ("cat", "head", "tail", "sed", "grep", "rg", "find", "ls", "awk", "less")
_BASH_GRAPH = ("graphify",)


def projects_dir() -> Path:
    """Claude Code's per-project transcript directory for a working tree."""
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return root / "projects"


def session_dir(cwd: str | None = None) -> Path | None:
    """Locate the transcript directory for `cwd`.

    Claude Code slugifies the absolute path by replacing every non-alphanumeric
    run with a dash, so /Users/x/Documents/p becomes -Users-x-Documents-p.
    """
    cwd = os.path.abspath(cwd or os.getcwd())
    slug = "".join(ch if ch.isalnum() else "-" for ch in cwd)
    d = projects_dir() / slug
    return d if d.is_dir() else None


def _classify_bash(cmd: str) -> str | None:
    """Bucket a shell command by its leading executable, or None to ignore it."""
    parts = cmd.strip().split()
    if not parts:
        return None
    # Step over env assignments and a leading `cd x &&` so the real command is
    # what gets classified.
    for tok in parts:
        t = tok.strip("(").lower()
        if "=" in t and not t.startswith("-"):
            continue
        if t in ("cd", "&&", ";", "|", "sudo", "then", "do"):
            continue
        base = os.path.basename(t)
        if base.startswith(_BASH_GRAPH):
            return "graph"
        if base in _BASH_READ:
            return "read"
        return "other"
    return None


def _bucket(name: str, inp: dict) -> str:
    """Map one tool call to a consumption bucket."""
    if name in GRAPH_TOOLS:
        return "graph"
    if name in READ_TOOLS:
        return "read"
    if name in SEARCH_TOOLS:
        return "search"
    if name == "Bash":
        cmd = (inp or {}).get("command") or ""
        # A graphify query issued through Bash belongs with graph traffic.
        return _classify_bash(cmd) or "other"
    return "other"


def parse_session(path: Path) -> dict:
    """Extract real usage and tool attribution from one transcript file.

    Streaming writes the same API call's usage block to several consecutive
    assistant rows, so summing rows double-counts (measured at ~2.1x on a real
    session). Usage is therefore keyed by message id and each id counted once.
    """
    usage_by_id: dict[str, dict] = {}
    order: list[str] = []
    # Tool calls are attributed to the message that requested them, then rolled
    # onto the *next* message's input cost below.
    tools_by_id: dict[str, list[str]] = {}
    model = None
    started = ended = None

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A live transcript can be mid-write; a torn last line is
                # normal and must not abort the read.
                continue

            ts = row.get("timestamp")
            if ts:
                started = started or ts
                ended = ts

            if row.get("type") != "assistant":
                continue
            msg = row.get("message") or {}
            mid = msg.get("id")
            if not mid:
                continue
            model = msg.get("model") or model

            usage = msg.get("usage")
            if usage and mid not in usage_by_id:
                usage_by_id[mid] = usage
                order.append(mid)

            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tools_by_id.setdefault(mid, []).append(
                            _bucket(block.get("name") or "", block.get("input") or {})
                        )

    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    buckets: dict[str, dict] = {}
    turns = []

    for i, mid in enumerate(order):
        u = usage_by_id[mid]
        inp = u.get("input_tokens", 0) or 0
        out = u.get("output_tokens", 0) or 0
        cr = u.get("cache_read_input_tokens", 0) or 0
        cw = u.get("cache_creation_input_tokens", 0) or 0
        totals["input"] += inp
        totals["output"] += out
        totals["cache_read"] += cr
        totals["cache_write"] += cw

        # Fresh (uncached) intake is the honest signal for "what did pulling
        # this content in cost": cache reads are mostly the conversation
        # replaying itself and would swamp any per-tool comparison.
        fresh = inp + cw
        turns.append({"id": mid, "input": inp, "output": out,
                      "cache_read": cr, "cache_write": cw, "fresh": fresh})

        # The previous message's tool calls are what put new content into this
        # call's context, so its fresh intake is charged to those buckets.
        prev = tools_by_id.get(order[i - 1]) if i else None
        if prev:
            share = fresh / len(prev)
            for b in prev:
                e = buckets.setdefault(b, {"tokens": 0.0, "calls": 0})
                e["tokens"] += share
                e["calls"] += 1

    for e in buckets.values():
        e["tokens"] = int(e["tokens"])

    cacheable = totals["cache_read"] + totals["cache_write"] + totals["input"]
    hit_rate = (totals["cache_read"] / cacheable * 100) if cacheable else 0.0

    return {
        "session": path.stem,
        "model": model,
        "started": started,
        "ended": ended,
        "mtime": path.stat().st_mtime,
        "api_calls": len(order),
        "totals": totals,
        "cache_hit_rate": round(hit_rate, 1),
        "buckets": buckets,
        "turns": turns[-60:],
    }


def payload(cwd: str | None = None, limit: int = 12) -> dict:
    """Aggregate every transcript for this project, newest session first."""
    d = session_dir(cwd)
    if not d:
        return {"error": "no Claude Code transcripts found for this project",
                "searched": str(projects_dir()), "sessions": []}

    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    sessions = []
    for f in files[:limit]:
        try:
            s = parse_session(f)
        except OSError:
            continue
        if s["api_calls"]:
            sessions.append(s)

    agg = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    agg_buckets: dict[str, dict] = {}
    for s in sessions:
        for k in agg:
            agg[k] += s["totals"][k]
        for name, e in s["buckets"].items():
            t = agg_buckets.setdefault(name, {"tokens": 0, "calls": 0})
            t["tokens"] += e["tokens"]
            t["calls"] += e["calls"]

    cacheable = agg["cache_read"] + agg["cache_write"] + agg["input"]
    return {
        "sessions": sessions,
        "all_time": {
            "totals": agg,
            "buckets": agg_buckets,
            "sessions": len(sessions),
            "cache_hit_rate": round(agg["cache_read"] / cacheable * 100, 1) if cacheable else 0.0,
        },
        # Surfaced in the UI so the dashboard states its own limits.
        "caveats": [
            "All token counts are server-reported from session transcripts, not estimated.",
            "Tool attribution is inferred from call ordering: a tool result is charged to the "
            "next API call. Sound in aggregate, approximate per call.",
            "No 'tokens saved' figure is shown: that needs the cost of the path not taken, "
            "which is a counterfactual and cannot be measured.",
        ],
    }
