---
name: rifflux-design
description: 'Design and implementation workflow for Rifflux local hybrid retrieval + MCP server in Python.'
---

# Rifflux Design Skill

Use this skill to plan or review Rifflux architecture and implementation choices.

## Inputs to gather
- Corpus size target (chunks/files)
- Primary content types (markdown only or mixed files)
- Latency target for top-k retrieval
- Whether sqlite-vec is allowed in target environments
- Preferred local embedding model/runtime

## Workflow
1. Define data model and chunk schema.
2. Validate markdown chunking rules (headings, fenced code blocks, breadcrumbs).
3. Define indexing pipeline (scan, chunk, embed, upsert, state tracking).
4. Define retrieval flows (FTS5, vector, fusion).
5. Validate ranking with RRF and return score breakdown.
6. Define MCP tool contracts and response schemas.
7. Propose MVP milestone slices with tests.

## Output format
- Short architecture summary
- Interface list (core + MCP)
- SQLite schema draft
- Ranking formula and tie-break policy
- Test plan (chunking, retrieval, fusion)
- Implementation milestone checklist

## Guardrails
- Prefer simple, explainable local-first defaults.
- Avoid cloud dependencies.
- Keep MCP transport isolated from retrieval core.
- Do not introduce vector DB infrastructure beyond SQLite + extension/fallback.
