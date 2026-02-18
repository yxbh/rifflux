from rifflux.indexing.chunker import chunk_markdown


def test_chunker_preserves_heading_and_code_block() -> None:
    text = """
# Intro

hello world paragraph

## Example

```python
print('hi')
```

some explanation after code
"""
    chunks = chunk_markdown(text, "docs/example.md", min_chunk_chars=10)
    assert chunks
    assert any("Example" in chunk.heading_path for chunk in chunks)
    assert any("```python" in chunk.content for chunk in chunks)
