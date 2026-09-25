# Working in this repo

## What to build next, and the tracker

Before you answer or edit anything in these cases, read `.agents/skills/product-manager/SKILL.md`. Then answer in its template and follow its rules. The cases:
- the user asks what to build, do or fix next, what's open, what's parked, or what to revisit;
- the user asks you to log, track or triage a bug, feature, piece of tech debt or run;
- you are about to edit `docs/TRACKER.md`, `docs/BACKLOG.md` or `docs/issues/`.

This applies whether or not anyone mentions a product manager. The tracker and backlog hold the items. The skill holds how to rank them, the answer's shape, and the rule that only the user brings parked work back.

The skill is the one definition every coding agent shares. Claude Code runs it as the `product-manager` agent, and Cursor has a pointer to it.

## Tracker

`docs/TRACKER.md` is the live list of everything open: tool bugs (B-), features (F-), tech debt and security (T-), and performance issues found in runs (P-, with files in `docs/issues/`).

- When you find a bug, ship something, or defer work, update the tracker in the same change, following the product-manager skill (above).
- Performance issues from runs are opened automatically after every recorded run (`swagperf/pm.py`). Don't open them by hand. To record a developer's decision, change the issue's `Status:` line (`confirmed`, `dismissed`, `expected`) and add a Log line with the reason.
- Long write-ups for deferred work go in `docs/BACKLOG.md`, linked from the tracker row.

## Wording

In anything a reader sees, call the memory metric "RAM usage" and its growth "RAM growth", never "RSS". The `rss` names in code and keys stay as they are, for schema stability.

Call a metric's threshold its "North Star target" (e.g. "Peak RAM usage over its North Star target: 493.3 MB vs 320 MB"), never its "budget". The time a single frame has to draw (16.67 ms at 60 Hz) is the "frame deadline". Code names and keys stay as they are, for schema stability: `budgets.py`, `budget:` signal keys, `budget_ms`, `over_budget`, `ttid_budget_ms`, `budget_breach`, and the `budgets` field in `apps.json`.
