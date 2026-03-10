"""Tests for easyapplybot.py bot logic."""

import csv
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from easyapplybot import DailyLimitReachedException, EasyApplyBot, ProfileConfig, _run_bot


# ---------------------------------------------------------------------------
# ProfileConfig model tests
# ---------------------------------------------------------------------------

class TestProfileConfig:
    def test_valid_config(self):
        config = ProfileConfig(
            email="test@example.com",
            password="secret",
            phone_number="555-1234",
            positions=["Software Engineer"],
            locations=["Remote"],
            remote_only=True,
            profile_url="https://linkedin.com/in/test",
            user_city="New York",
            user_state="NY",
            zip_code="10001",
            years_experience=5,
            desired_salary=120000,
            ai_provider="openai",
            ai_api_key="sk-test",
            blacklist=["Coinbase"],
            blacklist_titles=["intern"],
        )
        assert config.email == "test@example.com"
        assert config.password == "secret"
        assert config.phone_number == "555-1234"
        assert config.positions == ["Software Engineer"]
        assert config.locations == ["Remote"]
        assert config.remote_only is True
        assert config.years_experience == 5
        assert config.desired_salary == 120000
        assert config.ai_provider == "openai"
        assert config.ai_api_key == "sk-test"
        assert config.blacklist == ["Coinbase"]
        assert config.blacklist_titles == ["intern"]

    def test_defaults(self):
        config = ProfileConfig(email="a@b.com", password="pw")
        assert config.phone_number == ""
        assert config.positions == []
        assert config.locations == []
        assert config.remote_only is False
        assert config.profile_url == ""
        assert config.user_city == ""
        assert config.user_state == ""
        assert config.zip_code == ""
        assert config.years_experience == 0
        assert config.desired_salary == 0
        assert config.ai_provider == "openai"
        assert config.ai_api_key == ""
        assert config.blacklist == []
        assert config.blacklist_titles == []

    def test_missing_email_raises(self):
        with pytest.raises(ValidationError):
            ProfileConfig(password="pw")

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError):
            ProfileConfig(email="a@b.com")

    def test_json_round_trip(self):
        config = ProfileConfig(
            email="a@b.com",
            password="pw",
            positions=["Dev"],
            years_experience=3,
        )
        data = config.model_dump()
        restored = ProfileConfig(**data)
        assert restored.email == config.email
        assert restored.positions == config.positions
        assert restored.years_experience == config.years_experience

    def test_json_keys_are_snake_case(self):
        config = ProfileConfig(email="a@b.com", password="pw")
        data = config.model_dump()
        assert "phone_number" in data
        assert "remote_only" in data
        assert "profile_url" in data
        assert "user_city" in data
        assert "user_state" in data
        assert "blacklist" in data
        assert "blacklist_titles" in data
        assert "zip_code" in data
        assert "years_experience" in data
        assert "desired_salary" in data
        assert "ai_provider" in data
        assert "ai_api_key" in data

    def test_legacy_openai_api_key_migration(self):
        """Old profiles with openai_api_key should be silently migrated."""
        data = {
            "email": "a@b.com",
            "password": "pw",
            "openai_api_key": "sk-legacy",
        }
        config = ProfileConfig(**data)
        assert config.ai_api_key == "sk-legacy"
        assert config.ai_provider == "openai"
        assert not hasattr(config, "openai_api_key")


# ---------------------------------------------------------------------------
# get_appropriate_value tests (pure logic, no Selenium)
# ---------------------------------------------------------------------------

class TestGetAppropriateValue:
    """Test the field-filling heuristics without requiring Selenium."""

    def _make_bot_stub(self):
        """Create a stub that has the same attributes as EasyApplyBot
        without initializing Selenium."""
        stub = MagicMock()
        stub.phone_number = "555-9999"
        stub.location = "Knoxville, TN"
        stub.user_state = "Tennessee"
        stub.zip_code = "37923"
        stub.desired_salary = "100000"
        stub.years_of_experience = "3"
        stub.linkedin_profile_url = "https://linkedin.com/in/jamesparrish"
        stub.checked_invalid = False

        stub.get_appropriate_value = EasyApplyBot.get_appropriate_value.__get__(stub)
        stub.get_llm_suggested_answer = MagicMock(return_value="")
        return stub

    def test_phone_number(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Phone Number") == "555-9999"
        assert bot.get_appropriate_value("Mobile phone") == "555-9999"
        assert bot.get_appropriate_value("Contact telephone") == "555-9999"

    def test_city_location(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("City") == "Knoxville, TN"
        assert bot.get_appropriate_value("Current Location") == "Knoxville, TN"
        assert bot.get_appropriate_value("Where do you reside?") == "Knoxville, TN"

    def test_state(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("State") == "Tennessee"

    def test_zip_code(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Zip Code") == "37923"
        assert bot.get_appropriate_value("Postal code") == "37923"

    def test_salary(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Expected Salary") == "100000"
        assert bot.get_appropriate_value("Desired wage") == "100000"
        assert bot.get_appropriate_value("Annual income expectation") == "100000"

    def test_years_experience(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Years of experience") == "3"
        assert bot.get_appropriate_value("How many years experience do you have?") == "3"

    def test_availability(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("When are you available?") == "2 weeks"
        assert bot.get_appropriate_value("Start date") == "2 weeks"
        assert bot.get_appropriate_value("Notice period") == "2 weeks"

    def test_skills(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Key skills") == "Python, JavaScript, SQL"
        assert bot.get_appropriate_value("Programming language proficiency") == "Python, JavaScript, SQL"

    def test_education(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Highest education") == "Bachelor"
        assert bot.get_appropriate_value("Degree level") == "Bachelor"

    def test_linkedin_url(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("LinkedIn profile URL") == "https://linkedin.com/in/jamesparrish"

    def test_have_you_ever_worked(self):
        bot = self._make_bot_stub()
        assert bot.get_appropriate_value("Have you ever worked at this company?") == "No"

    def test_fallback_default(self):
        bot = self._make_bot_stub()
        result = bot.get_appropriate_value("Some random unknown field", "text")
        assert result == "3"

    def test_non_text_empty_fallback(self):
        bot = self._make_bot_stub()
        result = bot.get_appropriate_value("Some random unknown field", "radio")
        assert result == ""


# ---------------------------------------------------------------------------
# on_event callback tests
# ---------------------------------------------------------------------------

class TestOnEventCallback:
    """Test that EasyApplyBot calls the on_event callback correctly."""

    def _make_bot_stub_with_emit(self, on_event=None):
        """Create a bot stub with _emit bound, bypassing __init__."""
        stub = MagicMock()
        stub._on_event = on_event
        stub._emit = EasyApplyBot._emit.__get__(stub)
        return stub

    def test_emit_calls_on_event(self):
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        stub = self._make_bot_stub_with_emit(on_event=handler)
        stub._emit("test_event", {"key": "value"})

        assert len(events) == 1
        assert events[0] == ("test_event", {"key": "value"})

    def test_emit_with_no_callback(self):
        """_emit should be a no-op when on_event is None."""
        stub = self._make_bot_stub_with_emit(on_event=None)
        # Should not raise
        stub._emit("test_event", {"key": "value"})

    def test_emit_with_empty_data(self):
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        stub = self._make_bot_stub_with_emit(on_event=handler)
        stub._emit("login_success")

        assert len(events) == 1
        assert events[0] == ("login_success", {})

    def test_emit_callback_exception_is_swallowed(self):
        """Exceptions in the callback should not propagate."""
        def bad_handler(event_type, data):
            raise RuntimeError("callback error")

        stub = self._make_bot_stub_with_emit(on_event=bad_handler)
        # Should not raise
        stub._emit("test_event", {})


# ---------------------------------------------------------------------------
# _run_bot callback tests
# ---------------------------------------------------------------------------

class TestRunBotCallback:
    """Test that _run_bot fires bot_started/bot_stopped events."""

    def test_run_bot_fires_stopped_on_login_failure(self):
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        config = ProfileConfig(
            email="test@example.com",
            password="secret",
            positions=["SWE"],
            locations=["Remote"],
        )

        mock_bot = MagicMock()
        mock_bot.start_linkedin.return_value = False

        with patch("easyapplybot.EasyApplyBot", return_value=mock_bot):
            _run_bot(config, on_event=handler)

        event_types = [e[0] for e in events]
        assert "bot_stopped" in event_types
        stopped_event = next(e for e in events if e[0] == "bot_stopped")
        assert stopped_event[1].get("reason") == "login_failed"

    def test_run_bot_fires_bot_started_on_success(self):
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        config = ProfileConfig(
            email="test@example.com",
            password="secret",
            positions=["SWE"],
            locations=["Remote"],
        )

        mock_bot = MagicMock()
        mock_bot.start_linkedin.return_value = True
        mock_bot.start_apply.return_value = None

        with patch("easyapplybot.EasyApplyBot", return_value=mock_bot):
            _run_bot(config, on_event=handler)

        event_types = [e[0] for e in events]
        assert "bot_started" in event_types
        assert "bot_stopped" in event_types

    def test_run_bot_stopped_no_positions(self):
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        config = ProfileConfig(
            email="test@example.com",
            password="secret",
            positions=[],
            locations=[],
        )

        mock_bot = MagicMock()
        mock_bot.start_linkedin.return_value = True

        with patch("easyapplybot.EasyApplyBot", return_value=mock_bot):
            _run_bot(config, on_event=handler)

        event_types = [e[0] for e in events]
        assert "bot_stopped" in event_types
        stopped_event = next(e for e in events if e[0] == "bot_stopped")
        assert "no positions" in stopped_event[1].get("reason", "")


# ---------------------------------------------------------------------------
# Cross-platform compatibility tests
# ---------------------------------------------------------------------------

class TestCrossPlatformPaths:
    def test_log_directory_creation(self):
        import easyapplybot
        import inspect
        source = inspect.getsource(easyapplybot.setup_logger)
        assert "os.path.join" in source, "setup_logger should use os.path.join for paths"
        assert "os.makedirs" in source or "os.mkdir" in source

    def test_log_dir_can_be_created_in_temp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            assert os.path.isdir(log_dir)
            log_file = os.path.join(log_dir, "test.log")
            with open(log_file, "w") as f:
                f.write("test")
            assert os.path.isfile(log_file)

    def test_os_path_join_never_uses_wrong_separator(self):
        path = os.path.join("logs", "test.log")
        if sys.platform == "win32":
            assert "\\" in path
        else:
            assert "/" in path
            assert "\\" not in path


class TestCrossPlatformCSV:
    def test_csv_write_no_extra_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            tmppath = f.name
            writer = csv.writer(f)
            writer.writerow(["job1", "company1", "applied"])
            writer.writerow(["job2", "company2", "applied"])

        try:
            with open(tmppath, "r") as f:
                content = f.read()
            lines = content.strip().split("\n")
            assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {lines!r}"
            assert "" not in lines
        finally:
            os.unlink(tmppath)


class TestCrossPlatformPyautogui:
    def test_pyautogui_import_is_optional(self):
        import easyapplybot
        import inspect
        source = inspect.getsource(easyapplybot)
        assert "except ImportError" in source

    def test_avoid_lock_with_no_pyautogui(self):
        stub = MagicMock()
        stub.avoid_lock = EasyApplyBot.avoid_lock.__get__(stub)

        import easyapplybot
        original = easyapplybot.pyautogui
        try:
            easyapplybot.pyautogui = None
            stub.avoid_lock()
        finally:
            easyapplybot.pyautogui = original

    def test_avoid_lock_handles_display_error(self):
        stub = MagicMock()
        stub.avoid_lock = EasyApplyBot.avoid_lock.__get__(stub)

        mock_pyautogui = MagicMock()
        mock_pyautogui.FAILSAFE = True
        mock_pyautogui.position.side_effect = Exception("no display")

        import easyapplybot
        original = easyapplybot.pyautogui
        try:
            easyapplybot.pyautogui = mock_pyautogui
            stub.avoid_lock()
        finally:
            easyapplybot.pyautogui = original


class TestCrossPlatformJSONEncoding:
    def test_no_platform_line_endings_in_json(self):
        config = ProfileConfig(
            email="test@test.com",
            password="pass",
            positions=["SWE"],
            locations=["Remote", "New York"],
        )
        json_str = config.model_dump_json()
        assert "\r\n" not in json_str
        assert "\r" not in json_str

    def test_unicode_in_json(self):
        config = ProfileConfig(
            email="test@test.com",
            password="pass",
            user_city="San Jos\u00e9",
            positions=["D\u00e9veloppeur"],
        )
        data = json.loads(config.model_dump_json())
        assert data["user_city"] == "San Jos\u00e9"
        assert data["positions"][0] == "D\u00e9veloppeur"

    def test_empty_lists_serialize_correctly(self):
        config = ProfileConfig(email="a@b.com", password="pw")
        data = json.loads(config.model_dump_json())
        assert data["positions"] == []
        assert data["locations"] == []
        assert isinstance(data["positions"], list)


# ---------------------------------------------------------------------------
# LLM provider routing tests
# ---------------------------------------------------------------------------

class TestLLMProviderRouting:
    """Test that get_llm_suggested_answer routes to the correct helper."""

    def _make_bot_stub(self, provider="openai"):
        stub = MagicMock()
        stub.config = ProfileConfig(email="a@b.com", password="pw", ai_provider=provider)
        stub.location = "New York, NY"
        stub.years_of_experience = "5"
        stub.desired_salary = "120000"
        stub._build_llm_prompt = EasyApplyBot._build_llm_prompt.__get__(stub)
        stub._llm_openai = MagicMock(return_value="openai_answer")
        stub._llm_anthropic = MagicMock(return_value="anthropic_answer")
        stub._llm_gemini = MagicMock(return_value="gemini_answer")
        stub._llm_ollama = MagicMock(return_value="ollama_answer")
        stub.get_llm_suggested_answer = EasyApplyBot.get_llm_suggested_answer.__get__(stub)
        return stub

    def test_routes_to_openai(self):
        stub = self._make_bot_stub("openai")
        result = stub.get_llm_suggested_answer("Years of experience?")
        stub._llm_openai.assert_called_once()
        stub._llm_anthropic.assert_not_called()
        assert result == "openai_answer"

    def test_routes_to_anthropic(self):
        stub = self._make_bot_stub("anthropic")
        result = stub.get_llm_suggested_answer("Years of experience?")
        stub._llm_anthropic.assert_called_once()
        stub._llm_openai.assert_not_called()
        assert result == "anthropic_answer"

    def test_routes_to_gemini(self):
        stub = self._make_bot_stub("gemini")
        result = stub.get_llm_suggested_answer("Years of experience?")
        stub._llm_gemini.assert_called_once()
        stub._llm_openai.assert_not_called()
        assert result == "gemini_answer"

    def test_routes_to_ollama(self):
        stub = self._make_bot_stub("ollama")
        result = stub.get_llm_suggested_answer("Years of experience?")
        stub._llm_ollama.assert_called_once()
        stub._llm_openai.assert_not_called()
        assert result == "ollama_answer"

    def test_unknown_provider_returns_empty(self):
        stub = self._make_bot_stub("unknown")
        result = stub.get_llm_suggested_answer("Years of experience?")
        assert result == ""

    def test_exception_returns_empty(self):
        stub = self._make_bot_stub("openai")
        stub._llm_openai.side_effect = RuntimeError("API down")
        result = stub.get_llm_suggested_answer("Years of experience?")
        assert result == ""


# ---------------------------------------------------------------------------
# DailyLimitReachedException detection tests
# ---------------------------------------------------------------------------

class TestDailyLimitDetection:
    """Test daily limit detection and propagation."""

    def _make_bot_stub(self):
        stub = MagicMock()
        stub._check_daily_limit = EasyApplyBot._check_daily_limit.__get__(stub)
        return stub

    def _make_el(self, text):
        el = MagicMock()
        el.text = text
        return el

    def test_check_daily_limit_true(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.return_value = [
            self._make_el("We limit daily submissions to protect our members.")
        ]
        assert stub._check_daily_limit() is True

    def test_check_daily_limit_false_wrong_text(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.return_value = [
            self._make_el("Please enter a valid phone number.")
        ]
        assert stub._check_daily_limit() is False

    def test_check_daily_limit_false_no_elements(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.return_value = []
        assert stub._check_daily_limit() is False

    def test_check_daily_limit_case_insensitive(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.return_value = [
            self._make_el("WE LIMIT DAILY SUBMISSIONS.")
        ]
        assert stub._check_daily_limit() is True

    def test_check_daily_limit_matches_among_multiple_elements(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.return_value = [
            self._make_el("Please enter your phone number."),
            self._make_el("We limit daily submissions to protect our members."),
        ]
        assert stub._check_daily_limit() is True

    def test_check_daily_limit_exception_returns_false(self):
        stub = self._make_bot_stub()
        stub.browser.find_elements.side_effect = Exception("stale element")
        assert stub._check_daily_limit() is False

    def test_get_easy_apply_button_raises_preclick(self):
        """DailyLimitReachedException raised before button search when limit detected."""
        stub = MagicMock()
        stub._check_daily_limit.return_value = True
        stub.get_easy_apply_button = EasyApplyBot.get_easy_apply_button.__get__(stub)
        with pytest.raises(DailyLimitReachedException):
            stub.get_easy_apply_button()
        stub.browser.find_elements.assert_not_called()

    def test_get_easy_apply_button_raises_postclick(self):
        """DailyLimitReachedException raised after click when limit modal appears."""
        stub = MagicMock()
        # First call (pre-click) returns False, second call (post-click) returns True
        stub._check_daily_limit.side_effect = [False, True]
        stub.browser.find_elements.return_value = [MagicMock()]
        stub.get_easy_apply_button = EasyApplyBot.get_easy_apply_button.__get__(stub)
        with pytest.raises(DailyLimitReachedException):
            stub.get_easy_apply_button()

    def test_run_bot_emits_daily_limit_reached(self):
        """_run_bot emits daily_limit_reached and bot_stopped when limit is hit."""
        events = []
        def handler(event_type, data):
            events.append((event_type, data))

        config = ProfileConfig(
            email="test@example.com",
            password="secret",
            positions=["SWE"],
            locations=["Remote"],
        )

        mock_bot = MagicMock()
        mock_bot.start_linkedin.return_value = True
        mock_bot.start_apply.side_effect = DailyLimitReachedException("limit reached")

        with patch("easyapplybot.EasyApplyBot", return_value=mock_bot):
            _run_bot(config, on_event=handler)

        event_types = [e[0] for e in events]
        assert "daily_limit_reached" in event_types
        assert "bot_stopped" in event_types
        limit_event = next(e for e in events if e[0] == "daily_limit_reached")
        assert limit_event[1]["profile_email"] == "test@example.com"
        stopped_event = next(e for e in events if e[0] == "bot_stopped")
        assert stopped_event[1]["reason"] == "daily_limit_reached"
