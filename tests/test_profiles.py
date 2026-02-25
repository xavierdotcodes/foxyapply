"""Tests for profiles.py profile storage."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import profiles as prof


def make_temp_profiles(tmp_path):
    """Patch PROFILES_DIR and PROFILES_FILE to use a temp directory."""
    profiles_dir = tmp_path / ".hiringfunnel"
    profiles_file = profiles_dir / "profiles.json"
    return profiles_dir, profiles_file


# ---------------------------------------------------------------------------
# load_profiles
# ---------------------------------------------------------------------------

class TestLoadProfiles:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        _, profiles_file = make_temp_profiles(tmp_path)
        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.load_profiles()
        assert result == {}

    def test_loads_existing_profiles(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        data = {"Alice": {"email": "alice@example.com", "password": "pw"}}
        profiles_file.write_text(json.dumps(data), encoding="utf-8")

        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.load_profiles()
        assert result == data

    def test_invalid_json_returns_empty_dict(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text("not valid json", encoding="utf-8")

        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.load_profiles()
        assert result == {}


# ---------------------------------------------------------------------------
# save_profiles
# ---------------------------------------------------------------------------

class TestSaveProfiles:
    def test_creates_directory_if_missing(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.save_profiles({"Bob": {"email": "bob@example.com"}})

        assert profiles_dir.exists()
        assert profiles_file.exists()

    def test_round_trip(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)

        data = {"Carol": {"email": "carol@example.com", "password": "secret"}}
        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.save_profiles(data)
                result = prof.load_profiles()

        assert result == data

    def test_overwrites_existing(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(json.dumps({"Old": {}}), encoding="utf-8")

        new_data = {"New": {"email": "new@example.com"}}
        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.save_profiles(new_data)
                result = prof.load_profiles()

        assert "Old" not in result
        assert "New" in result


# ---------------------------------------------------------------------------
# upsert_profile
# ---------------------------------------------------------------------------

class TestUpsertProfile:
    def test_creates_new_profile(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.upsert_profile("Dave", {"email": "dave@example.com"})
                result = prof.load_profiles()

        assert "Dave" in result
        assert result["Dave"]["email"] == "dave@example.com"

    def test_updates_existing_profile(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(
            json.dumps({"Eve": {"email": "eve@example.com", "phone_number": "111"}}),
            encoding="utf-8",
        )

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.upsert_profile("Eve", {"email": "eve@example.com", "phone_number": "999"})
                result = prof.load_profiles()

        assert result["Eve"]["phone_number"] == "999"

    def test_preserves_other_profiles(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(
            json.dumps({"Frank": {"email": "frank@example.com"}}),
            encoding="utf-8",
        )

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.upsert_profile("Grace", {"email": "grace@example.com"})
                result = prof.load_profiles()

        assert "Frank" in result
        assert "Grace" in result


# ---------------------------------------------------------------------------
# delete_profile
# ---------------------------------------------------------------------------

class TestDeleteProfile:
    def test_deletes_existing_profile(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(
            json.dumps({"Hank": {"email": "hank@example.com"}}),
            encoding="utf-8",
        )

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                result = prof.delete_profile("Hank")
                remaining = prof.load_profiles()

        assert result is True
        assert "Hank" not in remaining

    def test_delete_nonexistent_returns_false(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                result = prof.delete_profile("Nobody")

        assert result is False

    def test_preserves_other_profiles_on_delete(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(
            json.dumps({
                "Ivy": {"email": "ivy@example.com"},
                "Jack": {"email": "jack@example.com"},
            }),
            encoding="utf-8",
        )

        with patch.object(prof, "PROFILES_DIR", profiles_dir):
            with patch.object(prof, "PROFILES_FILE", profiles_file):
                prof.delete_profile("Ivy")
                result = prof.load_profiles()

        assert "Ivy" not in result
        assert "Jack" in result


# ---------------------------------------------------------------------------
# list_names
# ---------------------------------------------------------------------------

class TestListNames:
    def test_empty_when_no_profiles(self, tmp_path):
        _, profiles_file = make_temp_profiles(tmp_path)
        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.list_names()
        assert result == []

    def test_returns_sorted_names(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(
            json.dumps({"Zoe": {}, "Alice": {}, "Bob": {}}),
            encoding="utf-8",
        )

        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.list_names()

        assert result == ["Alice", "Bob", "Zoe"]

    def test_single_profile(self, tmp_path):
        profiles_dir, profiles_file = make_temp_profiles(tmp_path)
        profiles_dir.mkdir(parents=True)
        profiles_file.write_text(json.dumps({"Solo": {}}), encoding="utf-8")

        with patch.object(prof, "PROFILES_FILE", profiles_file):
            result = prof.list_names()

        assert result == ["Solo"]
