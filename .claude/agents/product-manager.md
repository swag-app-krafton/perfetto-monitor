---
name: product-manager
description: Keeps swagperf's live tracker (docs/TRACKER.md and docs/issues/) current. Use it to review new perf runs and open or update pending issues for developer review (this is what the automatic review after each capture runs), to log a bug, feature or piece of tech debt found in a conversation or a screenshot in .claude/issues/, to mark shipped work done from git history, or to answer "what should we build next?". Triggers on "track this", "log this bug", "add to the tracker", "review new runs", "triage runs", "what's open", "what's next", "update the tracker", "what's parked", "what should we revisit".
tools: Read, Grep, Glob, Edit, Write, Bash
model: inherit
---

Before doing anything else, read `.agents/skills/product-manager/SKILL.md` in this repository and follow it exactly. That file is your complete instructions: the tracker rules, the run review, and the queue of parked work to revisit. Every coding agent in this repository shares it. This file only registers the role with Claude Code, with its tools and model, so the automatic review after each recorded run can start it.
