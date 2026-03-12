"""Tests for hiringfunnel.py TUI layer — DB integration and menu choices."""

from unittest.mock import patch, MagicMock

import pytest
import questionary

import db as db_module
from hiringfunnel import (
    BotState,
    PROFILE_FIELDS,
    build_menu_choices,
    prompt_profile_edit,
    _field_choice_label,
    _prompt_single_field,
    _open_linkedin_action,
)


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


# ---------------------------------------------------------------------------
# Helpers for edit-profile tests
# ---------------------------------------------------------------------------

def _idx(field_name: str) -> int:
    """Return the PROFILE_FIELDS index for a given field name."""
    return next(i for i, fd in enumerate(PROFILE_FIELDS) if fd[0] == field_name)


def _fd(field, label, kind, *extra):
    return (field, label, kind) + extra


# ---------------------------------------------------------------------------
# _field_choice_label
# ---------------------------------------------------------------------------

class TestFieldChoiceLabel:
    def test_label_prefix_is_field_label(self):
        fd = ("email", "Email address", "text")
        assert _field_choice_label(fd, {"email": "x@y.com"}).startswith("Email address: ")

    def test_text_value_shown(self):
        fd = ("email", "Email address", "text")
        label = _field_choice_label(fd, {"email": "user@example.com"})
        assert "user@example.com" in label

    def test_missing_field_shows_not_set(self):
        fd = ("email", "Email address", "text")
        assert "(not set)" in _field_choice_label(fd, {})

    def test_empty_string_shows_not_set(self):
        fd = ("email", "Email address", "text")
        assert "(not set)" in _field_choice_label(fd, {"email": ""})

    def test_long_value_truncated_with_ellipsis(self):
        fd = ("email", "Email address", "text")
        long_val = "a" * 50
        label = _field_choice_label(fd, {"email": long_val})
        assert "..." in label
        assert len(label) < len("Email address: " + long_val)

    def test_value_exactly_40_chars_not_truncated(self):
        fd = ("email", "Email address", "text")
        val = "a" * 40
        assert "..." not in _field_choice_label(fd, {"email": val})

    def test_password_masked_when_set(self):
        fd = ("password", "Password", "password")
        label = _field_choice_label(fd, {"password": "supersecret"})
        assert "••••••••" in label
        assert "supersecret" not in label

    def test_password_not_set_shows_not_set(self):
        fd = ("password", "Password", "password")
        assert "(not set)" in _field_choice_label(fd, {})

    def test_confirm_true_shows_yes(self):
        fd = ("remote_only", "Remote only?", "confirm")
        assert "Yes" in _field_choice_label(fd, {"remote_only": True})

    def test_confirm_false_shows_no(self):
        fd = ("remote_only", "Remote only?", "confirm")
        assert "No" in _field_choice_label(fd, {"remote_only": False})

    def test_list_joined_with_comma(self):
        fd = ("positions", "Positions", "text")
        label = _field_choice_label(fd, {"positions": ["SWE", "SRE"]})
        assert "SWE" in label
        assert "SRE" in label

    def test_empty_list_shows_empty(self):
        fd = ("positions", "Positions", "text")
        assert "(empty)" in _field_choice_label(fd, {"positions": []})

    def test_int_value_shown(self):
        fd = ("years_experience", "Years of experience", "text")
        assert "5" in _field_choice_label(fd, {"years_experience": 5})


# ---------------------------------------------------------------------------
# _prompt_single_field
# ---------------------------------------------------------------------------

class TestPromptSingleField:
    # --- text kind ---

    def test_text_returns_value(self):
        fd = ("email", "Email", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "new@example.com"
            cancelled, val = _prompt_single_field(fd, "old@example.com")
        assert cancelled is False
        assert val == "new@example.com"

    def test_text_cancelled_returns_true(self):
        fd = ("email", "Email", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = None
            cancelled, val = _prompt_single_field(fd, "")
        assert cancelled is True
        assert val is None

    def test_text_uses_current_as_default(self):
        fd = ("email", "Email", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "x@y.com"
            _prompt_single_field(fd, "old@example.com")
        m.assert_called_once_with("Email", default="old@example.com")

    def test_text_int_current_displayed_as_string(self):
        fd = ("years_experience", "Years", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "5"
            _prompt_single_field(fd, 3)
        m.assert_called_once_with("Years", default="3")

    def test_text_zero_int_displayed_as_empty_string(self):
        fd = ("years_experience", "Years", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "0"
            _prompt_single_field(fd, 0)
        m.assert_called_once_with("Years", default="")

    # --- list fields parsed ---

    def test_positions_field_parsed_to_list(self):
        fd = ("positions", "Positions", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "SWE, SRE"
            _, val = _prompt_single_field(fd, [])
        assert val == ["SWE", "SRE"]

    def test_blacklist_field_parsed_to_list(self):
        fd = ("blacklist", "Blacklist", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "Acme, Initech"
            _, val = _prompt_single_field(fd, [])
        assert val == ["Acme", "Initech"]

    def test_list_current_displayed_as_csv(self):
        fd = ("positions", "Positions", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "SWE"
            _prompt_single_field(fd, ["SWE", "SRE"])
        m.assert_called_once_with("Positions", default="SWE, SRE")

    # --- int fields parsed ---

    def test_years_experience_parsed_to_int(self):
        fd = ("years_experience", "Years", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "7"
            _, val = _prompt_single_field(fd, 0)
        assert val == 7

    def test_desired_salary_parsed_to_int(self):
        fd = ("desired_salary", "Salary", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "120000"
            _, val = _prompt_single_field(fd, 0)
        assert val == 120000

    def test_invalid_int_falls_back_to_zero(self):
        fd = ("years_experience", "Years", "text")
        with patch("hiringfunnel.questionary.text") as m:
            m.return_value.ask.return_value = "not-a-number"
            _, val = _prompt_single_field(fd, 0)
        assert val == 0

    # --- password kind ---

    def test_password_returns_value(self):
        fd = ("password", "Password", "password")
        with patch("hiringfunnel.questionary.password") as m:
            m.return_value.ask.return_value = "newpass"
            cancelled, val = _prompt_single_field(fd, "old")
        assert cancelled is False
        assert val == "newpass"

    def test_password_empty_input_keeps_current(self):
        fd = ("password", "Password", "password")
        with patch("hiringfunnel.questionary.password") as m:
            m.return_value.ask.return_value = ""
            _, val = _prompt_single_field(fd, "keepme")
        assert val == "keepme"

    def test_password_cancelled_returns_true(self):
        fd = ("password", "Password", "password")
        with patch("hiringfunnel.questionary.password") as m:
            m.return_value.ask.return_value = None
            cancelled, _ = _prompt_single_field(fd, "old")
        assert cancelled is True

    # --- confirm kind ---

    def test_confirm_returns_true(self):
        fd = ("remote_only", "Remote only?", "confirm")
        with patch("hiringfunnel.questionary.confirm") as m:
            m.return_value.ask.return_value = True
            cancelled, val = _prompt_single_field(fd, False)
        assert cancelled is False
        assert val is True

    def test_confirm_returns_false(self):
        fd = ("remote_only", "Remote only?", "confirm")
        with patch("hiringfunnel.questionary.confirm") as m:
            m.return_value.ask.return_value = False
            cancelled, val = _prompt_single_field(fd, True)
        assert cancelled is False
        assert val is False

    def test_confirm_uses_bool_current_as_default(self):
        fd = ("remote_only", "Remote only?", "confirm")
        with patch("hiringfunnel.questionary.confirm") as m:
            m.return_value.ask.return_value = True
            _prompt_single_field(fd, True)
        m.assert_called_once_with("Remote only?", default=True)

    def test_confirm_cancelled_returns_true(self):
        fd = ("remote_only", "Remote only?", "confirm")
        with patch("hiringfunnel.questionary.confirm") as m:
            m.return_value.ask.return_value = None
            cancelled, _ = _prompt_single_field(fd, False)
        assert cancelled is True

    # --- select kind ---

    def test_select_returns_chosen_value(self):
        fd = ("ai_provider", "AI provider", "select", ["openai", "anthropic"])
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "anthropic"
            cancelled, val = _prompt_single_field(fd, "openai")
        assert cancelled is False
        assert val == "anthropic"

    def test_select_valid_current_used_as_default(self):
        fd = ("ai_provider", "AI provider", "select", ["openai", "anthropic"])
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "anthropic"
            _prompt_single_field(fd, "anthropic")
        m.assert_called_once_with("AI provider", choices=["openai", "anthropic"], default="anthropic")

    def test_select_invalid_current_falls_back_to_first_choice(self):
        fd = ("ai_provider", "AI provider", "select", ["openai", "anthropic"])
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "openai"
            _prompt_single_field(fd, "invalid_value")
        _, kwargs = m.call_args
        assert kwargs["default"] == "openai"

    def test_select_cancelled_returns_true(self):
        fd = ("ai_provider", "AI provider", "select", ["openai", "anthropic"])
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = None
            cancelled, _ = _prompt_single_field(fd, "openai")
        assert cancelled is True


# ---------------------------------------------------------------------------
# prompt_profile_edit
# ---------------------------------------------------------------------------

class TestPromptProfileEdit:
    def _existing(self):
        return {
            "email": "test@example.com",
            "password": "pw",
            "phone_number": "555-0000",
            "positions": ["SWE"],
            "remote_only": False,
            "user_city": "Austin",
            "user_state": "TX",
        }

    def test_cancel_returns_none(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "cancel"
            assert prompt_profile_edit(self._existing()) is None

    def test_ctrlc_on_picker_returns_none(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = None
            assert prompt_profile_edit(self._existing()) is None

    def test_save_returns_dict(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit(self._existing())
        assert isinstance(result, dict)

    def test_save_preserves_unedited_fields(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit(self._existing())
        assert result["email"] == "test@example.com"
        assert result["positions"] == ["SWE"]

    def test_edit_text_field_updates_value(self):
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), "save"]
            mt.return_value.ask.return_value = "new@example.com"
            result = prompt_profile_edit(self._existing())
        assert result["email"] == "new@example.com"

    def test_edit_password_field_updates_value(self):
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.password") as mp:
            ms.return_value.ask.side_effect = [_idx("password"), "save"]
            mp.return_value.ask.return_value = "newpassword"
            result = prompt_profile_edit(self._existing())
        assert result["password"] == "newpassword"

    def test_edit_confirm_field_updates_value(self):
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.confirm") as mc:
            ms.return_value.ask.side_effect = [_idx("remote_only"), "save"]
            mc.return_value.ask.return_value = True
            result = prompt_profile_edit(self._existing())
        assert result["remote_only"] is True

    def test_edit_select_field_updates_value(self):
        # Both the picker and the inner ai_provider prompt use questionary.select.
        # side_effect order: picker → field index, inner prompt → new value, picker → "save"
        existing = {**self._existing(), "ai_provider": "openai"}
        with patch("hiringfunnel.questionary.select") as ms:
            ms.return_value.ask.side_effect = [_idx("ai_provider"), "anthropic", "save"]
            result = prompt_profile_edit(existing)
        assert result["ai_provider"] == "anthropic"

    def test_ctrlc_during_field_edit_returns_to_picker(self):
        """Cancelling a field prompt returns to picker; existing value is unchanged."""
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), "save"]
            mt.return_value.ask.return_value = None  # Ctrl+C during email edit
            result = prompt_profile_edit(self._existing())
        assert result is not None
        assert result["email"] == "test@example.com"  # unchanged

    def test_multiple_edits_before_save(self):
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), _idx("phone_number"), "save"]
            mt.return_value.ask.side_effect = ["new@example.com", "555-9999"]
            result = prompt_profile_edit(self._existing())
        assert result["email"] == "new@example.com"
        assert result["phone_number"] == "555-9999"

    def test_cancel_after_edits_discards_changes(self):
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), "cancel"]
            mt.return_value.ask.return_value = "new@example.com"
            result = prompt_profile_edit(self._existing())
        assert result is None

    def test_does_not_mutate_input_dict(self):
        existing = self._existing()
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), "save"]
            mt.return_value.ask.return_value = "changed@example.com"
            prompt_profile_edit(existing)
        assert existing["email"] == "test@example.com"

    # --- locations derivation ---

    def test_save_derives_locations_city_and_state(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit({**self._existing(), "user_city": "Austin", "user_state": "TX"})
        assert result["locations"] == ["Austin, TX"]

    def test_save_derives_locations_city_only(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit({**self._existing(), "user_city": "Austin", "user_state": ""})
        assert result["locations"] == ["Austin"]

    def test_save_derives_locations_state_only(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit({**self._existing(), "user_city": "", "user_state": "TX"})
        assert result["locations"] == ["TX"]

    def test_save_empty_city_state_gives_empty_locations(self):
        with patch("hiringfunnel.questionary.select") as m:
            m.return_value.ask.return_value = "save"
            result = prompt_profile_edit({**self._existing(), "user_city": "", "user_state": ""})
        assert result["locations"] == []

    # --- picker shows current values ---

    def test_picker_shows_current_field_values_in_labels(self):
        with patch("hiringfunnel.questionary.select") as ms:
            ms.return_value.ask.return_value = "cancel"
            prompt_profile_edit({"email": "shown@example.com"})
        choices = ms.call_args.kwargs["choices"]
        labels = [str(c.title) for c in choices if hasattr(c, "title")]
        assert any("shown@example.com" in lbl for lbl in labels)

    def test_picker_refreshes_value_after_edit(self):
        """Second picker render must show the updated value."""
        with patch("hiringfunnel.questionary.select") as ms, \
             patch("hiringfunnel.questionary.text") as mt:
            ms.return_value.ask.side_effect = [_idx("email"), "cancel"]
            mt.return_value.ask.return_value = "updated@example.com"
            prompt_profile_edit({"email": "old@example.com"})
        second_choices = ms.call_args_list[1].kwargs["choices"]
        labels = [str(c.title) for c in second_choices if hasattr(c, "title")]
        assert any("updated@example.com" in lbl for lbl in labels)

    def test_picker_has_save_and_cancel_options(self):
        with patch("hiringfunnel.questionary.select") as ms:
            ms.return_value.ask.return_value = "cancel"
            prompt_profile_edit(self._existing())
        choices = ms.call_args.kwargs["choices"]
        values = [c.value for c in choices if hasattr(c, "value")]
        assert "save" in values
        assert "cancel" in values

    def test_picker_has_entry_for_every_profile_field(self):
        with patch("hiringfunnel.questionary.select") as ms:
            ms.return_value.ask.return_value = "cancel"
            prompt_profile_edit(self._existing())
        choices = ms.call_args.kwargs["choices"]
        field_indices = [c.value for c in choices if hasattr(c, "value") and isinstance(c.value, int)]
        assert len(field_indices) == len(PROFILE_FIELDS)


# ---------------------------------------------------------------------------
# Open LinkedIn in browser — choice and handler
# ---------------------------------------------------------------------------

class TestOpenLinkedInChoice:
    def _existing(self):
        return {
            "email": "test@example.com",
            "password": "secret",
        }

    def test_open_linkedin_choice_present(self):
        with patch("hiringfunnel.questionary.select") as ms:
            ms.return_value.ask.return_value = "cancel"
            prompt_profile_edit(self._existing())
        choices = ms.call_args.kwargs["choices"]
        values = [c.value for c in choices if hasattr(c, "value")]
        assert "open_linkedin" in values

    def test_missing_email_shows_warning(self):
        with patch("hiringfunnel.console") as mc:
            _open_linkedin_action({"email": "", "password": "secret"})
        mc.print.assert_called_once()
        printed = mc.print.call_args.args[0]
        assert "email" in printed.lower() or "password" in printed.lower()

    def test_missing_password_shows_warning(self):
        with patch("hiringfunnel.console") as mc:
            _open_linkedin_action({"email": "user@example.com", "password": ""})
        mc.print.assert_called_once()
        printed = mc.print.call_args.args[0]
        assert "email" in printed.lower() or "password" in printed.lower()

    def test_success_shows_confirmation(self):
        def fake_thread(target=None, daemon=None):
            t = MagicMock()
            t.start = lambda: target()
            return t

        with patch("hiringfunnel.open_linkedin_profile", return_value=True), \
             patch("hiringfunnel.threading.Thread", side_effect=fake_thread), \
             patch("hiringfunnel.console") as mc:
            _open_linkedin_action(self._existing())
        printed_args = [call.args[0] for call in mc.print.call_args_list]
        assert any("Browser opened" in a or "green" in a for a in printed_args)

    def test_failure_shows_error(self):
        import threading

        def fake_thread(target=None, daemon=None):
            t = MagicMock()
            def start():
                target()
            t.start = start
            return t

        with patch("hiringfunnel.open_linkedin_profile", return_value=False), \
             patch("hiringfunnel.threading.Thread", side_effect=fake_thread), \
             patch("hiringfunnel.console") as mc:
            _open_linkedin_action(self._existing())
        printed_args = [call.args[0] for call in mc.print.call_args_list]
        assert any("red" in a or "Failed" in a for a in printed_args)

    def test_returns_to_loop_after_open(self):
        """After open_linkedin, picker is shown again (loop continues)."""
        import threading

        def fake_thread(target=None, daemon=None):
            t = MagicMock()
            def start():
                target()
            t.start = start
            return t

        with patch("hiringfunnel.open_linkedin_profile", return_value=True), \
             patch("hiringfunnel.threading.Thread", side_effect=fake_thread), \
             patch("hiringfunnel.console"), \
             patch("hiringfunnel.questionary.select") as ms:
            # First call: open_linkedin, second call: cancel
            ms.return_value.ask.side_effect = ["open_linkedin", "cancel"]
            result = prompt_profile_edit(self._existing())
        assert result is None  # cancelled on second loop
        assert ms.call_count == 2
