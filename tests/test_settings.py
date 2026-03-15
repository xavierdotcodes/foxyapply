"""Tests for settings.py — SystemConfig load/save/inject."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from settings import (
    SystemConfig,
    _inject_ai_env,
    load_settings,
    save_settings,
)


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------

def test_load_settings_missing_file(tmp_path):
    """Returns defaults when settings.json doesn't exist."""
    with patch("settings.SETTINGS_FILE", tmp_path / "settings.json"):
        cfg = load_settings()
    assert cfg.ai_provider == "openai"
    assert cfg.ai_api_key == ""


def test_load_settings_happy_path(tmp_path):
    """Reads ai_provider and ai_api_key from disk."""
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"ai_provider": "anthropic", "ai_api_key": "sk-ant-test"}))
    with patch("settings.SETTINGS_FILE", f):
        cfg = load_settings()
    assert cfg.ai_provider == "anthropic"
    assert cfg.ai_api_key == "sk-ant-test"


def test_load_settings_corrupt_file(tmp_path):
    """Returns defaults on JSON parse error."""
    f = tmp_path / "settings.json"
    f.write_text("NOT JSON")
    with patch("settings.SETTINGS_FILE", f):
        cfg = load_settings()
    assert cfg.ai_provider == "openai"


# ---------------------------------------------------------------------------
# save_settings / round-trip
# ---------------------------------------------------------------------------

def test_save_settings_round_trip(tmp_path):
    """save_settings writes a file that load_settings can read back."""
    f = tmp_path / "settings.json"
    cfg = SystemConfig(ai_provider="gemini", ai_api_key="goog-key")
    with patch("settings.SETTINGS_FILE", f), patch("settings.SETTINGS_DIR", tmp_path):
        save_settings(cfg)
        loaded = load_settings()
    assert loaded.ai_provider == "gemini"
    assert loaded.ai_api_key == "goog-key"


def test_save_settings_creates_dir(tmp_path):
    """save_settings creates missing parent directories."""
    nested = tmp_path / "a" / "b"
    f = nested / "settings.json"
    cfg = SystemConfig(ai_provider="openai", ai_api_key="sk-x")
    with patch("settings.SETTINGS_FILE", f), patch("settings.SETTINGS_DIR", nested):
        save_settings(cfg)
    assert f.exists()


# ---------------------------------------------------------------------------
# _inject_ai_env
# ---------------------------------------------------------------------------

def test_inject_sets_openai_key():
    cfg = SystemConfig(ai_provider="openai", ai_api_key="sk-open")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("HIRINGFUNNEL_AI_PROVIDER", None)
        _inject_ai_env(cfg)
        assert os.environ["OPENAI_API_KEY"] == "sk-open"
        assert os.environ["HIRINGFUNNEL_AI_PROVIDER"] == "openai"


def test_inject_sets_anthropic_key():
    cfg = SystemConfig(ai_provider="anthropic", ai_api_key="sk-ant")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("HIRINGFUNNEL_AI_PROVIDER", None)
        _inject_ai_env(cfg)
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant"


def test_inject_sets_gemini_key():
    cfg = SystemConfig(ai_provider="gemini", ai_api_key="goog-key")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("HIRINGFUNNEL_AI_PROVIDER", None)
        _inject_ai_env(cfg)
        assert os.environ["GOOGLE_API_KEY"] == "goog-key"


def test_inject_empty_key_does_not_overwrite():
    """Empty ai_api_key must not clobber an existing env var."""
    cfg = SystemConfig(ai_provider="openai", ai_api_key="")
    with patch.dict(os.environ, {"OPENAI_API_KEY": "already-set", "HIRINGFUNNEL_AI_PROVIDER": "openai"}):
        _inject_ai_env(cfg)
        assert os.environ["OPENAI_API_KEY"] == "already-set"


def test_inject_provider_setdefault_respects_existing():
    """Existing HIRINGFUNNEL_AI_PROVIDER takes precedence over settings.json value."""
    cfg = SystemConfig(ai_provider="openai", ai_api_key="")
    with patch.dict(os.environ, {"HIRINGFUNNEL_AI_PROVIDER": "anthropic"}):
        _inject_ai_env(cfg)
        assert os.environ["HIRINGFUNNEL_AI_PROVIDER"] == "anthropic"


def test_inject_unknown_provider_no_key_set():
    """Provider 'ollama' has no key env var — _inject_ai_env should not crash."""
    cfg = SystemConfig(ai_provider="ollama", ai_api_key="irrelevant")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HIRINGFUNNEL_AI_PROVIDER", None)
        _inject_ai_env(cfg)  # should not raise
        assert os.environ["HIRINGFUNNEL_AI_PROVIDER"] == "ollama"
