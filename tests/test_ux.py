"""Tests that ensure great user experience.

Covers: panel rendering, event→status message quality,
profile rotation logic, and menu display.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest
import questionary

from hiringfunnel import BotState, build_menu_choices, run_profile_sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_text(state: BotState) -> str:
    """Return the renderable body from state.render() as a plain string."""
    return str(state.render().renderable)


def _make_profiles(*names):
    """Build a minimal profiles dict for the given names."""
    return {
        name: {
            "email": f"{name}@example.com",
            "password": "pw",
            "positions": ["SWE"],
            "locations": ["Remote"],
        }
        for name in names
    }


class _RunBotTracker:
    """
    Callable that mocks _run_bot: fires pre-configured event sequences and
    records which profile emails it was called with.
    """
    def __init__(self, *event_sequences):
        self.call_emails: list = []
        self._sequences = event_sequences

    def __call__(self, cfg, on_event=None):
        idx = len(self.call_emails)
        self.call_emails.append(cfg.email)
        if on_event and idx < len(self._sequences):
            for event_type, data in self._sequences[idx]:
                on_event(event_type, data)

    @property
    def call_count(self):
        return len(self.call_emails)


# Reusable event sequence shortcuts
_COMPLETED = [("bot_stopped", {"reason": "completed"})]


def _daily_limit_for(email):
    return [
        ("daily_limit_reached", {"profile_email": email}),
        ("bot_stopped", {"reason": "daily_limit_reached"}),
    ]


class _SyncThread:
    """Drop-in for threading.Thread that runs the target synchronously."""
    def __init__(self, target=None, daemon=False):
        self._target = target

    def start(self):
        if self._target:
            self._target()

    def join(self, timeout=None):
        pass


def _run_sequence(start, all_names, profiles, tracker):
    """
    Call run_profile_sequence with all I/O and threading mocked.
    Returns list of strings passed to console.print.
    """
    live_ctx = MagicMock()
    live_ctx.__enter__ = MagicMock(return_value=MagicMock())
    live_ctx.__exit__ = MagicMock(return_value=False)

    with patch("hiringfunnel._redirect_logs_to_file"), \
         patch("hiringfunnel._run_bot", side_effect=tracker), \
         patch("hiringfunnel.Live", return_value=live_ctx), \
         patch("threading.Thread", _SyncThread), \
         patch("hiringfunnel.console") as mock_console:
        run_profile_sequence(start, all_names, profiles)

    return [str(c.args[0]) for c in mock_console.print.call_args_list]


# ---------------------------------------------------------------------------
# Panel rendering
# ---------------------------------------------------------------------------

class TestBotStateRender:
    def test_shows_profile_name(self):
        assert "Alice" in _render_text(BotState("Alice"))

    def test_shows_applied_count(self):
        state = BotState("p")
        state.applied = 7
        assert "7" in _render_text(state)

    def test_shows_failed_count(self):
        state = BotState("p")
        state.failed = 3
        assert "3" in _render_text(state)

    def test_shows_seen_count(self):
        state = BotState("p")
        state.seen = 42
        assert "42" in _render_text(state)

    def test_shows_status_message(self):
        state = BotState("p")
        state.status = "Logging in, please wait..."
        assert "Logging in, please wait..." in _render_text(state)

    def test_shows_log_entry(self):
        state = BotState("p")
        state.log_lines = ["  Applied: Backend Dev @ Acme"]
        assert "Backend Dev" in _render_text(state)

    def test_empty_log_lines_does_not_crash(self):
        assert BotState("p").render() is not None

    def test_panel_title_contains_hiringfunnel(self):
        assert "HiringFunnel" in str(BotState("p").render().title)

    def test_shows_only_last_10_of_many_log_lines(self):
        state = BotState("p")
        state.log_lines = [f"msg_{i}" for i in range(15)]
        rendered = _render_text(state)
        assert "msg_14" in rendered      # last line present
        assert "msg_0" not in rendered   # oldest lines absent

    def test_render_reflects_counters_after_event(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            state.on_event("job_applied", {"job_id": "1", "title": "SRE", "company": "X"})
        rendered = _render_text(state)
        assert "SRE" in rendered   # log line
        assert "1" in rendered     # applied count


# ---------------------------------------------------------------------------
# Event → user-facing status/log message quality
# ---------------------------------------------------------------------------

class TestBotStateEventMessages:
    def test_login_success_sets_nonempty_status(self):
        state = BotState("p")
        state.on_event("login_success", {})
        assert len(state.status) > 5

    def test_login_failed_status_reflects_error(self):
        state = BotState("p")
        state.on_event("login_failed", {"error": "bad credentials"})
        # Either the error message or "login" must appear so the user knows why
        assert "bad credentials" in state.status or "login" in state.status.lower()

    def test_login_failed_sets_stopped(self):
        state = BotState("p")
        state.on_event("login_failed", {"error": "timeout"})
        assert state.stopped is True

    def test_bot_started_status_is_action_oriented(self):
        state = BotState("p")
        state.on_event("bot_started", {})
        assert any(w in state.status.lower() for w in ("apply", "job", "search"))

    def test_bot_stopped_shows_reason_in_status(self):
        state = BotState("p")
        state.on_event("bot_stopped", {"reason": "completed"})
        assert "completed" in state.status.lower()

    def test_bot_stopped_sets_stopped_flag(self):
        state = BotState("p")
        state.on_event("bot_stopped", {"reason": "completed"})
        assert state.stopped is True

    def test_job_applying_status_shows_title(self):
        state = BotState("p")
        state.on_event("job_applying", {"title": "Staff Engineer", "company": "Stripe"})
        assert "Staff Engineer" in state.status

    def test_job_applying_status_shows_company(self):
        state = BotState("p")
        state.on_event("job_applying", {"title": "SWE", "company": "Stripe"})
        assert "Stripe" in state.status

    def test_job_applying_appends_to_log(self):
        state = BotState("p")
        state.on_event("job_applying", {"title": "SWE", "company": "Stripe"})
        assert any("SWE" in line for line in state.log_lines)

    def test_error_event_appends_message_to_log(self):
        state = BotState("p")
        state.on_event("error", {"message": "element not found"})
        assert any("element not found" in line for line in state.log_lines)

    def test_progress_updates_all_three_counters(self):
        state = BotState("p")
        state.on_event("progress", {"applied": 10, "failed": 2, "total_seen": 50})
        assert state.applied == 10
        assert state.failed == 2
        assert state.seen == 50

    def test_daily_limit_sets_flag(self):
        state = BotState("p")
        state.on_event("daily_limit_reached", {"profile_email": "x@y.com"})
        assert state.daily_limit_hit is True

    def test_daily_limit_status_mentions_email(self):
        state = BotState("p")
        state.on_event("daily_limit_reached", {"profile_email": "user@example.com"})
        assert "user@example.com" in state.status

    def test_daily_limit_missing_email_does_not_crash(self):
        state = BotState("p")
        state.on_event("daily_limit_reached", {})  # no profile_email key
        assert state.daily_limit_hit is True
        assert state.status  # non-empty fallback message

    def test_daily_limit_appends_to_log(self):
        state = BotState("p")
        state.on_event("daily_limit_reached", {"profile_email": "x@y.com"})
        assert any("daily limit" in line.lower() for line in state.log_lines)

    def test_log_buffer_never_exceeds_20(self):
        state = BotState("p")
        with patch("hiringfunnel.record_application"):
            for i in range(30):
                state.on_event("job_applied", {"job_id": str(i), "title": f"Job {i}", "company": "X"})
        assert len(state.log_lines) <= 20

    def test_unknown_event_does_not_crash(self):
        state = BotState("p")
        state.on_event("totally_unknown_event_xyz", {"data": "value"})  # must not raise


# ---------------------------------------------------------------------------
# Profile rotation logic
# ---------------------------------------------------------------------------

class TestRunProfileSequenceRotation:
    def test_single_profile_runs_once(self):
        tracker = _RunBotTracker(_COMPLETED)
        _run_sequence("alice", ["alice"], _make_profiles("alice"), tracker)
        assert tracker.call_count == 1

    def test_daily_limit_rotates_to_second_profile(self):
        tracker = _RunBotTracker(
            _daily_limit_for("alice@example.com"),
            _COMPLETED,
        )
        _run_sequence("alice", ["alice", "bob"], _make_profiles("alice", "bob"), tracker)
        assert tracker.call_count == 2

    def test_daily_limit_rotation_prints_next_profile_name(self):
        tracker = _RunBotTracker(
            _daily_limit_for("alice@example.com"),
            _COMPLETED,
        )
        printed = _run_sequence("alice", ["alice", "bob"], _make_profiles("alice", "bob"), tracker)
        assert any("bob" in line.lower() for line in printed)

    def test_no_rotation_on_clean_stop(self):
        tracker = _RunBotTracker(_COMPLETED)
        _run_sequence("alice", ["alice", "bob"], _make_profiles("alice", "bob"), tracker)
        assert tracker.call_count == 1

    def test_exhausted_profiles_prints_no_more_message(self):
        tracker = _RunBotTracker(_daily_limit_for("alice@example.com"))
        printed = _run_sequence("alice", ["alice"], _make_profiles("alice"), tracker)
        assert any("no more" in line.lower() for line in printed)

    def test_start_name_runs_first_regardless_of_sort_order(self):
        profiles = _make_profiles("alice", "bob", "carol")
        tracker = _RunBotTracker(
            _daily_limit_for("carol@example.com"),
            _daily_limit_for("alice@example.com"),
            _COMPLETED,
        )
        _run_sequence("carol", ["alice", "bob", "carol"], profiles, tracker)
        assert tracker.call_emails[0] == "carol@example.com"

    def test_each_rotation_uses_correct_profile_email(self):
        profiles = _make_profiles("alice", "bob", "carol")
        tracker = _RunBotTracker(
            _daily_limit_for("alice@example.com"),
            _daily_limit_for("bob@example.com"),
            _COMPLETED,
        )
        _run_sequence("alice", ["alice", "bob", "carol"], profiles, tracker)
        assert tracker.call_emails == [
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
        ]

    def test_invalid_profile_data_skipped_continues_to_valid(self):
        profiles = {
            "alice": {"email": "alice@example.com", "password": "pw", "positions": ["SWE"], "locations": ["Remote"]},
            "bad": {},  # missing required fields — ProfileConfig(**{}) raises ValidationError
            "bob": {"email": "bob@example.com", "password": "pw", "positions": ["SWE"], "locations": ["Remote"]},
        }
        tracker = _RunBotTracker(
            _daily_limit_for("alice@example.com"),
            _COMPLETED,
        )
        # Must not raise; "bad" is skipped; "bob" runs as the next valid profile
        _run_sequence("alice", ["alice", "bad", "bob"], profiles, tracker)
        assert "bob@example.com" in tracker.call_emails


# ---------------------------------------------------------------------------
# Menu UX
# ---------------------------------------------------------------------------

class TestMenuUX:
    def _run_choices(self, choices):
        return [c for c in choices if isinstance(c, questionary.Choice)
                and isinstance(c.value, tuple) and c.value[0] == "run"]

    def test_profile_name_visible_in_run_label(self):
        choices = build_menu_choices(["My Profile"], {})
        run = self._run_choices(choices)
        assert "My Profile" in str(run[0].title)

    def test_run_choices_appear_before_action_choices(self):
        choices = build_menu_choices(["alice", "bob"], {})
        run_indices = [i for i, c in enumerate(choices)
                       if isinstance(c, questionary.Choice)
                       and isinstance(c.value, tuple) and c.value[0] == "run"]
        action_indices = [i for i, c in enumerate(choices)
                          if isinstance(c, questionary.Choice)
                          and c.value in [("create", None), ("edit", None),
                                          ("delete", None), ("quit", None)]]
        assert max(run_indices) < min(action_indices)

    def test_separator_sits_between_profiles_and_actions(self):
        choices = build_menu_choices(["alice"], {})
        run_end = max(i for i, c in enumerate(choices)
                      if isinstance(c, questionary.Choice)
                      and isinstance(c.value, tuple) and c.value[0] == "run")
        action_start = min(i for i, c in enumerate(choices)
                           if isinstance(c, questionary.Choice)
                           and c.value in [("create", None), ("quit", None)])
        between = choices[run_end + 1:action_start]
        assert any(isinstance(c, questionary.Separator) for c in between)

    def test_no_profiles_shows_no_separator(self):
        choices = build_menu_choices([], {})
        assert not any(isinstance(c, questionary.Separator) for c in choices)

    def test_quit_always_present(self):
        values = [c.value for c in build_menu_choices([], {})
                  if isinstance(c, questionary.Choice)]
        assert ("quit", None) in values

    def test_create_edit_delete_always_present(self):
        values = [c.value for c in build_menu_choices([], {})
                  if isinstance(c, questionary.Choice)]
        assert ("create", None) in values
        assert ("edit", None) in values
        assert ("delete", None) in values
