"""Tests for db.py — SQLite application tracking."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import db as db_module


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Patch DB_PATH to a temp file and initialize the schema."""
    db_file = tmp_path / "test.db"
    with patch.object(db_module, "DB_PATH", db_file):
        db_module.init_db()
        yield db_file


def _read_all(db_file: Path) -> list:
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM applications ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_applications_table(self, tmp_path):
        db_file = tmp_path / "test.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()

        conn = sqlite3.connect(str(db_file))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='applications'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_table_has_correct_columns(self, tmp_path):
        db_file = tmp_path / "test.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()

        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(applications)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert columns == {"id", "profile_name", "job_id", "title", "company", "status", "applied_at"}

    def test_idempotent(self, tmp_path):
        db_file = tmp_path / "test.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()
            db_module.init_db()  # must not raise

    def test_creates_parent_directory(self, tmp_path):
        db_file = tmp_path / "nested" / "dir" / "test.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()
        assert db_file.exists()

    def test_empty_table_after_init(self, tmp_db):
        rows = _read_all(tmp_db)
        assert rows == []


# ---------------------------------------------------------------------------
# record_application
# ---------------------------------------------------------------------------

class TestRecordApplication:
    def test_inserts_one_row(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "123", "SWE", "Acme", "applied")
        rows = _read_all(tmp_db)
        assert len(rows) == 1

    def test_row_fields_match(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "123", "SWE", "Acme Corp", "applied")
        row = _read_all(tmp_db)[0]
        assert row["profile_name"] == "alice"
        assert row["job_id"] == "123"
        assert row["title"] == "SWE"
        assert row["company"] == "Acme Corp"
        assert row["status"] == "applied"

    def test_applied_at_is_valid_iso8601(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "123", "SWE", "Acme", "applied")
        row = _read_all(tmp_db)[0]
        # Should parse without raising
        parsed = datetime.fromisoformat(row["applied_at"])
        assert parsed.tzinfo is not None  # UTC-aware

    def test_applied_at_is_recent(self, tmp_db):
        before = datetime.now(timezone.utc)
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "123", "SWE", "Acme", "applied")
        after = datetime.now(timezone.utc)
        row = _read_all(tmp_db)[0]
        ts = datetime.fromisoformat(row["applied_at"])
        assert before <= ts <= after

    def test_inserts_failed_status(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("bob", "999", "PM", "Initech", "failed")
        row = _read_all(tmp_db)[0]
        assert row["status"] == "failed"

    def test_multiple_rows_accumulate(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SRE", "B", "applied")
            db_module.record_application("alice", "3", "PM", "C", "failed")
        rows = _read_all(tmp_db)
        assert len(rows) == 3

    def test_empty_optional_fields_allowed(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "", "", "", "applied")
        rows = _read_all(tmp_db)
        assert len(rows) == 1
        assert rows[0]["job_id"] == ""
        assert rows[0]["title"] == ""
        assert rows[0]["company"] == ""

    def test_unicode_fields(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("José", "42", "Développeur", "Société Générale", "applied")
        row = _read_all(tmp_db)[0]
        assert row["profile_name"] == "José"
        assert row["title"] == "Développeur"
        assert row["company"] == "Société Générale"

    def test_rows_have_auto_incrementing_ids(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("a", "1", "T", "C", "applied")
            db_module.record_application("a", "2", "T", "C", "applied")
        rows = _read_all(tmp_db)
        assert rows[0]["id"] == 1
        assert rows[1]["id"] == 2

    def test_different_profiles_stored_independently(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("bob", "2", "PM", "B", "failed")
        rows = _read_all(tmp_db)
        names = {r["profile_name"] for r in rows}
        assert names == {"alice", "bob"}


# ---------------------------------------------------------------------------
# get_profile_stats
# ---------------------------------------------------------------------------

class TestGetProfileStats:
    def test_returns_zeros_for_unknown_profile(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            stats = db_module.get_profile_stats("nobody")
        assert stats == {"applied": 0, "failed": 0}

    def test_counts_applied(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SRE", "B", "applied")
            stats = db_module.get_profile_stats("alice")
        assert stats["applied"] == 2
        assert stats["failed"] == 0

    def test_counts_failed(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "failed")
            stats = db_module.get_profile_stats("alice")
        assert stats["applied"] == 0
        assert stats["failed"] == 1

    def test_counts_both(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SWE", "B", "applied")
            db_module.record_application("alice", "3", "PM", "C", "failed")
            stats = db_module.get_profile_stats("alice")
        assert stats["applied"] == 2
        assert stats["failed"] == 1

    def test_ignores_other_profiles(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("bob", "2", "PM", "B", "applied")
            db_module.record_application("bob", "3", "PM", "C", "applied")
            stats = db_module.get_profile_stats("alice")
        assert stats["applied"] == 1

    def test_returns_int_not_none(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            stats = db_module.get_profile_stats("empty_profile")
        assert isinstance(stats["applied"], int)
        assert isinstance(stats["failed"], int)

    def test_large_count(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            for i in range(100):
                db_module.record_application("alice", str(i), "SWE", "Acme", "applied")
            stats = db_module.get_profile_stats("alice")
        assert stats["applied"] == 100

    def test_profile_name_case_sensitive(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("Alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SWE", "B", "applied")
            alice_stats = db_module.get_profile_stats("alice")
            Alice_stats = db_module.get_profile_stats("Alice")
        assert alice_stats["applied"] == 1
        assert Alice_stats["applied"] == 1


# ---------------------------------------------------------------------------
# get_all_stats
# ---------------------------------------------------------------------------

class TestGetAllStats:
    def test_empty_db_returns_empty_dict(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            stats = db_module.get_all_stats()
        assert stats == {}

    def test_single_profile_applied_only(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SWE", "B", "applied")
            stats = db_module.get_all_stats()
        assert stats == {"alice": {"applied": 2, "failed": 0}}

    def test_single_profile_failed_only(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "failed")
            stats = db_module.get_all_stats()
        assert stats == {"alice": {"applied": 0, "failed": 1}}

    def test_single_profile_mixed(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SWE", "B", "failed")
            stats = db_module.get_all_stats()
        assert stats["alice"] == {"applied": 1, "failed": 1}

    def test_multiple_profiles(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("alice", "2", "SWE", "B", "applied")
            db_module.record_application("bob", "3", "PM", "C", "applied")
            db_module.record_application("bob", "4", "PM", "D", "failed")
            stats = db_module.get_all_stats()
        assert stats["alice"] == {"applied": 2, "failed": 0}
        assert stats["bob"] == {"applied": 1, "failed": 1}

    def test_profiles_are_isolated(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            db_module.record_application("bob", "2", "PM", "B", "applied")
            stats = db_module.get_all_stats()
        assert "alice" in stats
        assert "bob" in stats
        assert stats["alice"]["applied"] == 1
        assert stats["bob"]["applied"] == 1

    def test_unknown_status_not_counted(self, tmp_db):
        """Rows with an unrecognized status are silently excluded from counts."""
        db_file = tmp_db
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "INSERT INTO applications (profile_name, job_id, title, company, status, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("alice", "1", "SWE", "A", "skipped", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        with patch.object(db_module, "DB_PATH", db_file):
            stats = db_module.get_all_stats()
        assert stats["alice"] == {"applied": 0, "failed": 0}

    def test_stats_values_are_ints(self, tmp_db):
        with patch.object(db_module, "DB_PATH", tmp_db):
            db_module.record_application("alice", "1", "SWE", "A", "applied")
            stats = db_module.get_all_stats()
        assert isinstance(stats["alice"]["applied"], int)
        assert isinstance(stats["alice"]["failed"], int)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_writes(self, tmp_db):
        """Multiple threads writing simultaneously must not lose rows."""
        n_threads = 10
        writes_per_thread = 20
        errors = []

        def write_rows():
            try:
                for i in range(writes_per_thread):
                    with patch.object(db_module, "DB_PATH", tmp_db):
                        db_module.record_application("alice", str(i), "SWE", "Acme", "applied")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_rows) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        rows = _read_all(tmp_db)
        assert len(rows) == n_threads * writes_per_thread

    def test_concurrent_reads_and_writes(self, tmp_db):
        """Reads during concurrent writes must not raise."""
        errors = []

        def write_rows():
            for i in range(10):
                try:
                    with patch.object(db_module, "DB_PATH", tmp_db):
                        db_module.record_application("alice", str(i), "SWE", "A", "applied")
                except Exception as e:
                    errors.append(("write", e))

        def read_stats():
            for _ in range(10):
                try:
                    with patch.object(db_module, "DB_PATH", tmp_db):
                        db_module.get_profile_stats("alice")
                except Exception as e:
                    errors.append(("read", e))

        threads = (
            [threading.Thread(target=write_rows) for _ in range(3)]
            + [threading.Thread(target=read_stats) for _ in range(3)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
