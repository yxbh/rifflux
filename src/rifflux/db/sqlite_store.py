from __future__ import annotations

import sqlite3
import re
from pathlib import Path
from typing import Any

import numpy as np


class SqliteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self, schema_path: Path) -> None:
        sql = schema_path.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self.conn.commit()

    def get_file_meta(self, path: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT id, mtime_ns, size_bytes, sha256 FROM files WHERE path = ?",
            (path,),
        )
        return cur.fetchone()

    def upsert_file(self, path: str, mtime_ns: int, size_bytes: int, sha256: str) -> int:
        self.conn.execute(
            """
            INSERT INTO files(path, mtime_ns, size_bytes, sha256)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              mtime_ns = excluded.mtime_ns,
              size_bytes = excluded.size_bytes,
              sha256 = excluded.sha256
            """,
            (path, mtime_ns, size_bytes, sha256),
        )
        cur = self.conn.execute("SELECT id FROM files WHERE path = ?", (path,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not resolve file id after upsert")
        return int(row["id"])

    def delete_chunks_for_file(self, file_id: int) -> None:
        self.conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def insert_chunk(
        self,
        *,
        chunk_id: str,
        file_id: int,
        chunk_index: int,
        heading_path: str,
        content: str,
        token_count: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO chunks(chunk_id, file_id, chunk_index, heading_path, content, token_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, file_id, chunk_index, heading_path, content, token_count),
        )

    def insert_embedding(self, *, chunk_id: str, model: str, vector: np.ndarray) -> None:
        arr = np.asarray(vector, dtype=np.float32)
        self.conn.execute(
            """
                        INSERT INTO embeddings(chunk_id, model, dim, vec)
                        VALUES (?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
              model = excluded.model,
              dim = excluded.dim,
                            vec = excluded.vec,
              updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
                        (chunk_id, model, int(arr.shape[0]), arr.tobytes()),
        )

    def commit(self) -> None:
        self.conn.commit()

    def set_metadata(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO index_metadata(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (key, value),
        )

    def get_metadata(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM index_metadata WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            return None
        return str(row["value"])

    def delete_metadata(self, key: str) -> None:
        self.conn.execute("DELETE FROM index_metadata WHERE key = ?", (key,))

    def delete_files_except(self, paths: list[str]) -> int:
        if not paths:
            cur = self.conn.execute("SELECT COUNT(*) FROM files")
            count = int(cur.fetchone()[0])
            self.conn.execute("DELETE FROM files")
            return count

        placeholders = ", ".join(["?"] * len(paths))
        cur = self.conn.execute(
            f"SELECT COUNT(*) FROM files WHERE path NOT IN ({placeholders})",
            tuple(paths),
        )
        count = int(cur.fetchone()[0])
        self.conn.execute(
            f"DELETE FROM files WHERE path NOT IN ({placeholders})",
            tuple(paths),
        )
        return count

    def index_status(self) -> dict[str, int]:
        file_count = int(self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        chunk_count = int(self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        embedding_count = int(self.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])
        return {
            "files": file_count,
            "chunks": chunk_count,
            "embeddings": embedding_count,
        }

    def lexical_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        sql = """
            SELECT
              c.chunk_id,
              f.path,
              c.heading_path,
              c.chunk_index,
              c.content,
              bm25(chunks_fts) AS bm25_score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN files f ON f.id = c.file_id
            WHERE chunks_fts MATCH ?
            ORDER BY bm25(chunks_fts)
            LIMIT ?
            """
        compiled_query = _compile_fts_query(query)
        if compiled_query is None:
            return []

        try:
            cur = self.conn.execute(sql, (compiled_query, top_k))
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as exc:
            if not _is_fts_query_error(exc):
                raise

            safe_query = _normalize_fts_query(query)
            if safe_query is None:
                return []

            cur = self.conn.execute(sql, (safe_query, top_k))
            return [dict(row) for row in cur.fetchall()]

    def all_embeddings(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT
              e.chunk_id,
              e.dim,
                            e.vec AS vector,
              f.path,
              c.heading_path,
              c.chunk_index,
              c.content
            FROM embeddings e
            JOIN chunks c ON c.chunk_id = e.chunk_id
            JOIN files f ON f.id = c.file_id
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            """
            SELECT c.chunk_id, f.path, c.heading_path, c.chunk_index, c.content
            FROM chunks c
            JOIN files f ON f.id = c.file_id
            WHERE c.chunk_id = ?
            """,
            (chunk_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_file(self, path: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            """
            SELECT c.chunk_id, c.heading_path, c.chunk_index, c.content
            FROM chunks c
            JOIN files f ON f.id = c.file_id
            WHERE f.path = ?
            ORDER BY c.chunk_index ASC
            """,
            (path,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return None
        return {"path": path, "chunks": rows}


def _normalize_fts_query(query: str) -> str | None:
    terms = [token for token in re.findall(r"\w+", query, flags=re.UNICODE) if token]
    if not terms:
        return None
    return " ".join(terms)


def _compile_fts_query(query: str) -> str | None:
    terms = [token for token in re.findall(r"\w+", query, flags=re.UNICODE) if token]
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)


def _is_fts_query_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return (
        "fts5:" in message
        or "no such column" in message
        or "unterminated string" in message
        or "malformed match" in message
        or "syntax error" in message
    )
