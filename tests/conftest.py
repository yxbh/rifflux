from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.helpers import write_search_fixture_corpus


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
