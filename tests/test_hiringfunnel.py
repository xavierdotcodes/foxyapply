"""Tests for hiringfunnel.py TUI layer — DB integration and menu choices."""

from unittest.mock import patch, MagicMock

import pytest
import questionary

import db as db_module
from hiringfunnel import BotState, build_menu_choices


# ---------------------------------------------------------------------------
# BotState.on_event → record_application integration
# ---------------------------------------------------------------------------

class TestBotStateRecordsToDb:
    def test_job_applied_calls_record_application(self):
        state = BotState("test_profile")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_applied", {"job_id": "123", "title": "SWE", "company": "Acme"})
        mock_record.assert_called_once_with("test_profile", "123", "SWE", "Acme", "applied")

    def test_job_failed_calls_record_application(self):
        state = BotState("test_profile")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_failed", {"job_id": "456", "title": "PM", "company": "Initech"})
        mock_record.assert_called_once_with("test_profile", "456", "PM", "Initech", "failed")

    def test_applied_uses_correct_status(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_applied", {"job_id": "1", "title": "T", "company": "C"})
        _, _, _, _, status = mock_record.call_args.args
        assert status == "applied"

    def test_failed_uses_correct_status(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_failed", {"job_id": "2", "title": "T", "company": "C"})
        _, _, _, _, status = mock_record.call_args.args
        assert status == "failed"

    def test_applied_passes_profile_name(self):
        state = BotState("my_profile")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_applied", {"job_id": "1", "title": "T", "company": "C"})
        profile_name = mock_record.call_args.args[0]
        assert profile_name == "my_profile"

    def test_missing_fields_default_to_empty_string(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("job_applied", {})
        mock_record.assert_called_once_with("p", "", "", "", "applied")

    def test_other_events_do_not_record(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application") as mock_record:
            state.on_event("bot_started", {})
            state.on_event("bot_stopped", {"reason": "completed"})
            state.on_event("login_success", {})
            state.on_event("login_failed", {"error": "timeout"})
            state.on_event("progress", {"applied": 5, "failed": 1, "total_seen": 10})
            state.on_event("error", {"message": "oops"})
            state.on_event("job_applying", {"job_id": "99", "title": "T", "company": "C"})
        mock_record.assert_not_called()

    def test_record_failure_does_not_crash_state(self):
        """If record_application raises, on_event must still update in-memory state."""
        state = BotState("p")
        with patch("hiringfunnel.record_application", side_effect=OSError("disk full")):
            # Should not raise
            state.on_event("job_applied", {"job_id": "1", "title": "SWE", "company": "Acme"})
        assert state.applied == 1  # in-memory count still incremented

    def test_job_applied_increments_applied_count(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            state.on_event("job_applied", {"job_id": "1", "title": "SWE", "company": "A"})
            state.on_event("job_applied", {"job_id": "2", "title": "SWE", "company": "B"})
        assert state.applied == 2

    def test_job_failed_increments_failed_count(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            state.on_event("job_failed", {"job_id": "1", "title": "SWE", "company": "A"})
        assert state.failed == 1

    def test_job_applied_appends_to_log(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            state.on_event("job_applied", {"job_id": "1", "title": "Backend Dev", "company": "A"})
        assert any("Backend Dev" in line for line in state.log_lines)

    def test_job_failed_appends_to_log(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            state.on_event("job_failed", {"job_id": "1", "title": "Frontend Dev", "company": "A"})
        assert any("Frontend Dev" in line for line in state.log_lines)


# ---------------------------------------------------------------------------
# build_menu_choices — stats display
# ---------------------------------------------------------------------------

def _run_choices(choices):
    """Extract only Choice objects with a 'run' action."""
    return [c for c in choices if isinstance(c, questionary.Choice) and
            isinstance(c.value, tuple) and c.value[0] == "run"]


class TestBuildMenuChoicesStats:
    def test_no_profiles_no_run_choices(self):
        choices = build_menu_choices([], {})
        run = _run_choices(choices)
        assert run == []

    def test_shows_applied_count_in_label(self):
        stats = {"alice": {"applied": 7, "failed": 2}}
        choices = build_menu_choices(["alice"], stats)
        run = _run_choices(choices)
        assert len(run) == 1
        assert "7" in str(run[0].title)
        assert "applied" in str(run[0].title)

    def test_zero_when_profile_not_in_stats(self):
        choices = build_menu_choices(["newprofile"], {})
        run = _run_choices(choices)
        assert "0" in str(run[0].title)

    def test_zero_when_profile_has_no_applied(self):
        stats = {"alice": {"applied": 0, "failed": 3}}
        choices = build_menu_choices(["alice"], stats)
        run = _run_choices(choices)
        assert "0" in str(run[0].title)

    def test_value_tuple_still_correct(self):
        stats = {"alice": {"applied": 5, "failed": 0}}
        choices = build_menu_choices(["alice"], stats)
        run = _run_choices(choices)
        assert run[0].value == ("run", "alice")

    def test_multiple_profiles_each_show_own_count(self):
        stats = {
            "alice": {"applied": 10, "failed": 0},
            "bob": {"applied": 3, "failed": 1},
        }
        choices = build_menu_choices(["alice", "bob"], stats)
        run = _run_choices(choices)
        alice_choice = next(c for c in run if c.value == ("run", "alice"))
        bob_choice = next(c for c in run if c.value == ("run", "bob"))
        assert "10" in str(alice_choice.title)
        assert "3" in str(bob_choice.title)

    def test_non_run_choices_still_present(self):
        choices = build_menu_choices(["alice"], {"alice": {"applied": 1, "failed": 0}})
        values = [c.value for c in choices if isinstance(c, questionary.Choice)]
        assert ("create", None) in values
        assert ("edit", None) in values
        assert ("delete", None) in values
        assert ("quit", None) in values

    def test_default_stats_arg_is_empty(self):
        """Calling with only names (no stats) must not raise."""
        choices = build_menu_choices(["alice"])
        run = _run_choices(choices)
        assert len(run) == 1
        assert "0" in str(run[0].title)


# ---------------------------------------------------------------------------
# End-to-end: real DB written via BotState, read back via get_profile_stats
# ---------------------------------------------------------------------------

class TestEndToEndDbIntegration:
    def test_applied_events_persist_to_db(self, tmp_path):
        db_file = tmp_path / "e2e.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()
            state = BotState("e2e_profile")
            state.on_event("job_applied", {"job_id": "1", "title": "SWE", "company": "A"})
            state.on_event("job_applied", {"job_id": "2", "title": "SRE", "company": "B"})
            state.on_event("job_failed", {"job_id": "3", "title": "PM", "company": "C"})
            stats = db_module.get_profile_stats("e2e_profile")

        assert stats["applied"] == 2
        assert stats["failed"] == 1

    def test_stats_appear_in_menu_after_run(self, tmp_path):
        db_file = tmp_path / "e2e.db"
        with patch.object(db_module, "DB_PATH", db_file):
            db_module.init_db()
            state = BotState("my_profile")
            for i in range(5):
                state.on_event("job_applied", {"job_id": str(i), "title": "SWE", "company": "X"})
            all_stats = db_module.get_all_stats()

        choices = build_menu_choices(["my_profile"], all_stats)
        run = _run_choices(choices)
        assert "5" in str(run[0].title)
