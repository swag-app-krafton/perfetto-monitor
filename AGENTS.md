# Working in this repo

## Tracker

`docs/TRACKER.md` is the live list of everything open: tool bugs (B-), features (F-), tech debt and security (T-), and performance issues found in runs (P-, with files in `docs/issues/`).

- When you find a bug, ship something, or defer work, update the tracker in the same change. You can also hand it to the product-manager agent (`.claude/agents/product-manager.md`), which follows the tracker's rules for IDs, statuses and priorities.
- Performance issues from runs are opened automatically after every recorded run (`swagperf/pm.py`). Don't open them by hand. To record a developer's decision, change the issue's `Status:` line (`confirmed`, `dismissed`, `expected`) and add a Log line with the reason.
- Long write-ups for deferred work go in `docs/BACKLOG.md`, linked from the tracker row.

## Wording

In anything a reader sees, call the memory metric "RAM usage" and its growth "RAM growth", never "RSS". The `rss` names in code and keys stay as they are, for schema stability.
