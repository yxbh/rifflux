import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_PATH = Path(".tmp") / "rifflux" / "rifflux.db"


def _env(name: str, default: str) -> str:
    return os.getenv(f"RIFFLUX_{name}", default)


def _parse_glob_list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class RiffluxConfig:
    db_path: Path = DEFAULT_DB_PATH
    max_chunk_chars: int = 2000
    min_chunk_chars: int = 120
    rrf_k: int = 60
    embedding_backend: str = "auto"
    embedding_dim: int = 384
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    index_include_globs: tuple[str, ...] = ("*.md",)
    index_exclude_globs: tuple[str, ...] = (
        ".git/*",
        ".venv/*",
        "**/__pycache__/*",
        "**/.pytest_cache/*",
        "**/.ruff_cache/*",
        "**/node_modules/*",
    )
    auto_reindex_on_search: bool = False
    auto_reindex_paths: tuple[str, ...] = (".",)
    auto_reindex_min_interval_seconds: float = 2.0
    file_watcher_enabled: bool = False
    file_watcher_paths: tuple[str, ...] = ()
    file_watcher_debounce_ms: int = 500

    @classmethod
    def from_env(cls) -> "RiffluxConfig":
        db_path = Path(_env("DB_PATH", str(DEFAULT_DB_PATH)))
        max_chunk_chars = int(_env("MAX_CHUNK_CHARS", "2000"))
        min_chunk_chars = int(_env("MIN_CHUNK_CHARS", "120"))
        rrf_k = int(_env("RRF_K", "60"))
        embedding_backend = _env("EMBEDDING_BACKEND", "auto")
        embedding_dim = int(_env("EMBEDDING_DIM", "384"))
        embedding_model = _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        index_include_globs = _parse_glob_list(_env("INDEX_INCLUDE_GLOBS", "*.md"))
        index_exclude_globs = _parse_glob_list(
            _env(
                "INDEX_EXCLUDE_GLOBS",
                ".git/*,.venv/*,**/__pycache__/*,**/.pytest_cache/*,**/.ruff_cache/*,**/node_modules/*",
            )
        )
        auto_reindex_on_search = _parse_bool(
            _env("AUTO_REINDEX_ON_SEARCH", "0")
        )
        auto_reindex_paths = _parse_glob_list(
            _env("AUTO_REINDEX_PATHS", ".")
        )
        auto_reindex_min_interval_seconds = float(
            _env("AUTO_REINDEX_MIN_INTERVAL_SECONDS", "2.0")
        )
        file_watcher_enabled = _parse_bool(
            _env("FILE_WATCHER", "0")
        )
        file_watcher_paths = _parse_glob_list(
            _env("FILE_WATCHER_PATHS", "")
        )
        file_watcher_debounce_ms = int(
            _env("FILE_WATCHER_DEBOUNCE_MS", "500")
        )
        return cls(
            db_path=db_path,
            max_chunk_chars=max_chunk_chars,
            min_chunk_chars=min_chunk_chars,
            rrf_k=rrf_k,
            embedding_backend=embedding_backend,
            embedding_dim=embedding_dim,
            embedding_model=embedding_model,
            index_include_globs=index_include_globs,
            index_exclude_globs=index_exclude_globs,
            auto_reindex_on_search=auto_reindex_on_search,
            auto_reindex_paths=auto_reindex_paths,
            auto_reindex_min_interval_seconds=auto_reindex_min_interval_seconds,
            file_watcher_enabled=file_watcher_enabled,
            file_watcher_paths=file_watcher_paths,
            file_watcher_debounce_ms=file_watcher_debounce_ms,
        )
