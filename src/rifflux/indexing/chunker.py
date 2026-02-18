from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import mistune


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    chunk_index: int
    heading_path: str
    content: str
    token_count: int


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def make_chunk_id(path: str, chunk_index: int) -> str:
    raw = f"{normalize_path(path)}::{chunk_index}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _extract_text(node: dict) -> str:
    if "raw" in node and isinstance(node["raw"], str):
        return node["raw"]
    text_parts: list[str] = []
    for child in node.get("children", []) or []:
        text_parts.append(_extract_text(child))
    return "".join(text_parts)


def chunk_markdown(
    markdown_text: str,
    relative_path: str,
    *,
    max_chunk_chars: int = 2000,
    min_chunk_chars: int = 120,
) -> list[Chunk]:
    parser = mistune.create_markdown(renderer="ast")
    ast = parser(markdown_text)
    heading_stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = [("", [])]

    for node in ast:
        node_type = node.get("type", "")
        if node_type == "heading":
            level = int(node.get("attrs", {}).get("level", 1))
            text = _extract_text(node).strip()
            heading_stack = [h for h in heading_stack if h[0] < level]
            heading_stack.append((level, text))
            heading_path = " > ".join(part for _, part in heading_stack if part)
            sections.append((heading_path, []))
            continue

        if node_type == "block_code":
            attrs = node.get("attrs", {}) or {}
            info = attrs.get("info") or ""
            code_body = node.get("raw", "")
            block = f"```{info}\n{code_body}\n```".strip()
            sections[-1][1].append(block)
            continue

        text = _extract_text(node).strip()
        if text:
            sections[-1][1].append(text)

    chunks: list[Chunk] = []
    chunk_index = 0
    for heading_path, parts in sections:
        if not parts:
            continue
        current = ""
        for part in parts:
            proposal = part if not current else f"{current}\n\n{part}"
            if len(proposal) <= max_chunk_chars:
                current = proposal
                continue
            if len(current) >= min_chunk_chars:
                chunks.append(
                    Chunk(
                        chunk_id=make_chunk_id(relative_path, chunk_index),
                        chunk_index=chunk_index,
                        heading_path=heading_path,
                        content=current.strip(),
                        token_count=len(re.findall(r"\S+", current)),
                    )
                )
                chunk_index += 1
            current = part

        if len(current.strip()) >= min_chunk_chars:
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(relative_path, chunk_index),
                    chunk_index=chunk_index,
                    heading_path=heading_path,
                    content=current.strip(),
                    token_count=len(re.findall(r"\S+", current)),
                )
            )
            chunk_index += 1

    return chunks
