---
name: graphify-query-first
description: Routes natural-language questions about a repository, architecture, symbols, dependencies, data flow, or project behavior through an existing Graphify graph before broad source exploration. Apply whenever graphify-out/graph.json exists, regardless of the selected model or provider.
---

# Graphify Query First

Use an existing Graphify graph as the first retrieval layer for codebase understanding.

## Routing policy

1. Check for `graphify-out/graph.json` in the repository root.
2. If it exists and the request asks how the codebase works, run:

   ```bash
   graphify query "<user question>" --budget 1200
   ```

3. Use default BFS for broad architecture questions. Use `--dfs` only for a specific execution or dependency path.
4. Answer from the bounded graph context first. Cite `source_location` for concrete claims.
5. Read only the specific source files needed to verify a claim or fill an identified graph gap.

Do not run corpus detection, extraction, clustering, or visualization when a graph already exists. Do not rebuild or update unless the user explicitly requests it.

## Exceptions

Skip graph retrieval when:

- the user requests a direct edit to explicitly named files and no codebase discovery is needed;
- the request is unrelated to repository contents;
- the user explicitly asks not to use Graphify;
- the graph is missing or unreadable.

If the graph is stale, disclose the recorded and current revisions. It may still be used for orientation, but verify affected claims against source.

If `graphify query` is unavailable, use the installed Graphify query fallback against `graphify-out/graph.json`; do not load the entire JSON into the conversation.

## Context discipline

- Keep the query budget at 1,200 tokens unless the user asks for more.
- Do not paste full graph reports or full source files into context.
- Prefer one focused graph query over several broad repository scans.
- Treat `EXTRACTED`, `INFERRED`, and `AMBIGUOUS` provenance honestly; never invent an edge.
