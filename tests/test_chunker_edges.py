from rifflux.indexing.chunker import chunk_markdown, make_chunk_id, normalize_path


def test_normalize_path_converts_separators() -> None:
    assert normalize_path("\\docs\\guide\\intro.md") == "docs/guide/intro.md"


def test_chunk_id_is_deterministic() -> None:
    left = make_chunk_id("docs/a.md", 0)
    right = make_chunk_id("docs/a.md", 0)
    assert left == right
    assert len(left) == 16


def test_nested_heading_breadcrumbs_are_preserved() -> None:
    text = """
# Top

top text with enough words to become chunk content.

## Mid

mid text with enough words to become chunk content.

### Leaf

leaf text with enough words to become chunk content.
"""
    chunks = chunk_markdown(text, "docs/heads.md", min_chunk_chars=10)
    heading_paths = {chunk.heading_path for chunk in chunks}
    assert "Top" in heading_paths
    assert "Top > Mid" in heading_paths
    assert "Top > Mid > Leaf" in heading_paths


def test_min_chunk_chars_filters_small_fragments() -> None:
    text = """
# Tiny

small

## Big

This section has enough content to survive filtering and should remain.
"""
    chunks = chunk_markdown(text, "docs/filter.md", min_chunk_chars=40)
    assert all("small" not in chunk.content for chunk in chunks)
    assert any("survive filtering" in chunk.content for chunk in chunks)
