#!/usr/bin/env python3
"""Inject Graphify query-first context before each prompt when a graph exists."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def workspace_roots(event: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    for raw in event.get("workspace_roots", []):
        if isinstance(raw, str) and raw:
            roots.append(Path(raw))

    project_dir = os.environ.get("CURSOR_PROJECT_DIR")
    if project_dir:
        candidate = Path(project_dir)
        if candidate not in roots:
            roots.append(candidate)

    return roots


def current_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def graph_metadata(path: Path) -> tuple[str | None, bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, False
    built_at = data.get("built_at_commit")
    return (built_at if isinstance(built_at, str) and built_at else None), True


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        emit({"continue": True})
        return 0

    matches: list[tuple[Path, str | None, str | None]] = []
    for root in workspace_roots(event):
        graph_path = root / "graphify-out" / "graph.json"
        if not graph_path.is_file():
            continue
        built_at, readable = graph_metadata(graph_path)
        if readable:
            matches.append((root, built_at, current_commit(root)))

    if not matches:
        emit({"continue": True})
        return 0

    repository_notes = []
    for root, built_at, head in matches:
        revision = "revision unknown"
        if built_at and head:
            revision = "current revision" if built_at == head else f"stale: graph {built_at[:12]}, source {head[:12]}"
        elif built_at:
            revision = f"graph revision {built_at[:12]}"
        repository_notes.append(f"{root.name} ({revision})")

    context = (
        "GRAPHIFY QUERY-FIRST PRE-PROMPT POLICY: An existing graph is available for "
        + ", ".join(repository_notes)
        + ". Apply the graphify-query-first skill. For repository-understanding questions, "
        "run `graphify query \"<user question>\" --budget 1200` before broad file search/read; "
        "use graph context first, cite source_location, then read only targeted files for verification. "
        "Do not rebuild automatically. Skip graph retrieval for direct edits to explicitly named files, "
        "non-repository requests, or when the user opts out. This policy is independent of the selected model."
    )
    emit({"continue": True, "additional_context": context})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
