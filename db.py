"""SQLite persistence for job application tracking."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".hiringfunnel" / "hiringfunnel.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the applications table if it does not exist. Idempotent."""
    with closing(_connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_name TEXT NOT NULL,
                job_id       TEXT,
                title        TEXT,
                company      TEXT,
                status       TEXT NOT NULL,
                applied_at   TEXT NOT NULL
            )
        """)
        conn.commit()


def record_application(
    profile_name: str,
    job_id: str,
    title: str,
    company: str,
    status: str,
) -> None:
    """Insert one application row. status should be 'applied' or 'failed'."""
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO applications "
            "(profile_name, job_id, title, company, status, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                profile_name,
                job_id,
                title,
                company,
                status,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_profile_stats(profile_name: str) -> dict:
    """Return {applied: int, failed: int} for a single profile."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT "
            "  SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied, "
            "  SUM(CASE WHEN status = 'failed'  THEN 1 ELSE 0 END) AS failed "
            "FROM applications WHERE profile_name = ?",
            (profile_name,),
        ).fetchone()
    return {
        "applied": int(row["applied"] or 0),
        "failed": int(row["failed"] or 0),
    }


def get_all_stats() -> dict:
    """Return {profile_name: {applied: int, failed: int}} for all profiles."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT profile_name, status, COUNT(*) AS cnt "
            "FROM applications "
            "GROUP BY profile_name, status"
        ).fetchall()
    stats: dict = {}
    for row in rows:
        name = row["profile_name"]
        if name not in stats:
            stats[name] = {"applied": 0, "failed": 0}
        if row["status"] in ("applied", "failed"):
            stats[name][row["status"]] = row["cnt"]
    return stats
