PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    submitter_name TEXT NOT NULL,
    submitter_email TEXT NOT NULL,
    title TEXT NOT NULL,
    composer TEXT NOT NULL,
    work TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    sub_category TEXT NOT NULL DEFAULT '',
    voice_count TEXT NOT NULL DEFAULT '',
    voice_types TEXT NOT NULL DEFAULT '',
    tonality TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    lyrics_original TEXT NOT NULL DEFAULT '',
    lyrics_translation TEXT NOT NULL DEFAULT '',
    copyright_confirmed INTEGER NOT NULL CHECK (copyright_confirmed = 1),
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    file_size INTEGER NOT NULL CHECK (file_size > 0),
    submitted_at TEXT NOT NULL,
    reviewed_at TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    published_item_id INTEGER,
    published_filename TEXT
);

DROP INDEX IF EXISTS idx_submissions_status_submitted_at;

CREATE INDEX IF NOT EXISTS idx_submissions_status_submitted_at_id
ON submissions(status, submitted_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_submissions_sha256
ON submissions(sha256);

CREATE TABLE IF NOT EXISTS catalog_items (
    item_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    composer TEXT NOT NULL,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'approved' CHECK (status = 'approved'),
    source_submission_id INTEGER,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    synced_at TEXT NOT NULL,
    FOREIGN KEY (source_submission_id) REFERENCES submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_items_status
ON catalog_items(status);
