-- RabbitSoftware sync service: structured data in Cloudflare D1 (SQLite).
-- R2 keeps the blobs (device keys, encrypted history, public corpus batches); D1 holds what needs queries.
-- Nothing here identifies a person: shared answers carry no account or device, and the corpus is public.

-- Answers users chose to share for training the next model, with the owner's review.
CREATE TABLE training_answers (
  id           TEXT PRIMARY KEY,                       -- random UUID
  shared_at    TEXT NOT NULL,                          -- ISO 8601, UTC
  question     TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
  answer       TEXT NOT NULL CHECK (length(answer) BETWEEN 1 AND 4000),
  sources      TEXT NOT NULL DEFAULT '[]',             -- JSON array of up to 10 URLs
  rating       INTEGER NOT NULL CHECK (rating IN (-1, 0, 1)),
  model        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  reviewed_at  TEXT,
  exported_in  TEXT REFERENCES exports(file)           -- the export file that carried it to Hugging Face
);
CREATE INDEX training_by_status ON training_answers (status, shared_at);
CREATE INDEX training_unexported ON training_answers (exported_in, shared_at);

-- Public research records from every device: one row per record, deduplicated across batches.
CREATE TABLE corpus_records (
  source        TEXT NOT NULL,
  external_id   TEXT NOT NULL,
  title         TEXT NOT NULL,
  abstract      TEXT NOT NULL DEFAULT '',
  source_url    TEXT NOT NULL,
  published_at  TEXT NOT NULL DEFAULT '',
  batch         TEXT NOT NULL,                         -- the R2 batch it first arrived in
  added_at      TEXT NOT NULL,
  PRIMARY KEY (source, external_id)
);
CREATE INDEX corpus_by_added ON corpus_records (added_at);

-- Each export of shared answers to the private Hugging Face dataset.
CREATE TABLE exports (
  file        TEXT PRIMARY KEY,                        -- e.g. data/2026-10-01.parquet
  created_at  TEXT NOT NULL,
  rows        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  hf_commit   TEXT NOT NULL DEFAULT ''
);
