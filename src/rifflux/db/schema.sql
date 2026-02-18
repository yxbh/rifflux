PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  mtime_ns INTEGER NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  chunk_id TEXT NOT NULL UNIQUE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_file_idx ON chunks(file_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content,
  heading_path,
  chunk_id UNINDEXED,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vec BLOB NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS index_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content, heading_path, chunk_id)
  VALUES (new.id, new.content, new.heading_path, new.chunk_id);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content, heading_path, chunk_id)
  VALUES('delete', old.id, old.content, old.heading_path, old.chunk_id);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content, heading_path, chunk_id)
  VALUES('delete', old.id, old.content, old.heading_path, old.chunk_id);
  INSERT INTO chunks_fts(rowid, content, heading_path, chunk_id)
  VALUES (new.id, new.content, new.heading_path, new.chunk_id);
END;
