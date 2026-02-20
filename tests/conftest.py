from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.helpers import write_search_fixture_corpus


@pytest.fixture(autouse=True)
def _clear_tools_caches():
    """Reset module-level caches in mcp.tools between tests."""
    from rifflux.mcp.tools import _clear_caches
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def schema_sql_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "rifflux" / "db" / "schema.sql"


@pytest.fixture
def make_db_path(tmp_path: Path) -> Callable[[str], Path]:
    def _factory(name: str = "rifflux.db") -> Path:
        return tmp_path / name

    return _factory


@pytest.fixture
def fixture_corpus_path(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    write_search_fixture_corpus(corpus)
    return corpus
