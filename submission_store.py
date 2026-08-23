"""SQLite persistence for the local submission and review workflow."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parent
SCHEMA_FILE = ROOT / "db" / "schema.sql"
DB_PATH = ROOT / os.environ.get("SUBMISSIONS_DB", "submissions.db")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


@contextmanager
def database(db_path: Path | str = DB_PATH):
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database(db_path: Path | str = DB_PATH) -> None:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    with database(db_path) as connection:
        connection.executescript(schema)
        connection.execute("PRAGMA optimize")


def sync_catalog(items: Iterable[Mapping[str, object]], db_path: Path | str = DB_PATH) -> None:
    """Mirror the currently published JSON catalog as approved records."""
    synced_at = now_utc()
    rows = [
        (
            int(item["id"]),
            str(item["public_id"]),
            str(item.get("title", "")),
            str(item.get("composer", "")),
            str(item.get("category", "")),
            str(item.get("filename", "")),
            synced_at,
        )
        for item in items
    ]
    with database(db_path) as connection:
        connection.execute("UPDATE catalog_items SET is_current = 0")
        connection.executemany(
            """
            INSERT INTO catalog_items (
                item_id, public_id, title, composer, category, filename,
                status, is_current, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'approved', 1, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                public_id = excluded.public_id,
                title = excluded.title,
                composer = excluded.composer,
                category = excluded.category,
                filename = excluded.filename,
                status = 'approved',
                is_current = 1,
                synced_at = excluded.synced_at
            """,
            rows,
        )
        connection.execute("DELETE FROM catalog_items WHERE is_current = 0")
        connection.execute("PRAGMA optimize")


def create_submission(values: Mapping[str, object], db_path: Path | str = DB_PATH) -> int:
    columns = (
        "public_id", "status", "submitter_name", "submitter_email", "title",
        "composer", "work", "language", "category", "sub_category",
        "voice_count", "voice_types", "tonality", "description",
        "lyrics_original", "lyrics_translation", "copyright_confirmed",
        "original_filename", "stored_filename", "sha256", "file_size",
        "submitted_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    with database(db_path) as connection:
        cursor = connection.execute(
            f"INSERT INTO submissions ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        return int(cursor.lastrowid)


def get_submission(submission_id: int, db_path: Path | str = DB_PATH) -> dict | None:
    with database(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
    return dict(row) if row else None


def find_active_duplicate(sha256: str, db_path: Path | str = DB_PATH) -> dict | None:
    with database(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, public_id, status, title
            FROM submissions
            WHERE sha256 = ? AND status IN ('pending', 'approved')
            ORDER BY id DESC
            LIMIT 1
            """,
            (sha256,),
        ).fetchone()
    return dict(row) if row else None


def list_submissions(status: str = "pending", db_path: Path | str = DB_PATH) -> list[dict]:
    query = "SELECT * FROM submissions"
    params: tuple[object, ...] = ()
    if status in {"pending", "approved", "rejected"}:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY submitted_at DESC, id DESC"
    with database(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def submission_counts(db_path: Path | str = DB_PATH) -> dict[str, int]:
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    with database(db_path) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS total FROM submissions GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["total"])
    return counts


def mark_approved(
    submission_id: int,
    item_id: int,
    filename: str,
    review_note: str,
    db_path: Path | str = DB_PATH,
) -> None:
    reviewed_at = now_utc()
    with database(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE submissions
            SET status = 'approved', reviewed_at = ?, review_note = ?,
                published_item_id = ?, published_filename = ?
            WHERE id = ? AND status = 'pending'
            """,
            (reviewed_at, review_note, item_id, filename, submission_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("投稿状态已变化，请刷新后重试")
        catalog_cursor = connection.execute(
            """
            UPDATE catalog_items
            SET source_submission_id = ?, filename = ?, synced_at = ?
            WHERE item_id = ?
            """,
            (submission_id, filename, reviewed_at, item_id),
        )
        if catalog_cursor.rowcount != 1:
            connection.execute(
                """
                INSERT INTO catalog_items (
                    item_id, public_id, title, composer, category, filename,
                    status, source_submission_id, is_current, synced_at
                )
                SELECT ?, public_id, title, composer, category, ?,
                       'approved', id, 1, ?
                FROM submissions WHERE id = ?
                """,
                (item_id, filename, reviewed_at, submission_id),
            )


def mark_rejected(
    submission_id: int,
    review_note: str,
    db_path: Path | str = DB_PATH,
) -> None:
    with database(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE submissions
            SET status = 'rejected', reviewed_at = ?, review_note = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_utc(), review_note, submission_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("投稿状态已变化，请刷新后重试")


def restore_pending(submission_id: int, db_path: Path | str = DB_PATH) -> None:
    with database(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE submissions
            SET status = 'pending', reviewed_at = NULL, review_note = ''
            WHERE id = ? AND status = 'rejected'
            """,
            (submission_id,),
        )
        if cursor.rowcount != 1:
            raise ValueError("只有已驳回的投稿可以恢复为待审核")
