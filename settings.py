"""System-level configuration for HiringFunnel.

Stored at ~/.hiringfunnel/settings.json, separate from per-profile data.

# Load/inject flow:
#
#   _run_bot()
#     → load_settings()          reads this file; returns SystemConfig defaults
#                                 if the file is missing or corrupt
#     → _inject_ai_env(settings)  sets os.environ BEFORE EasyApplyBot is constructed
#     → EasyApplyBot(config, ...) reads provider/key from os.environ (unchanged)
#
# Precedence: existing env vars (including values loaded from .env by load_dotenv)
# take precedence over settings.json because _inject_ai_env uses setdefault for the
# provider name. The API key uses a non-empty guard so it never overwrites an
# existing env var with an empty string.
"""

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

SETTINGS_DIR = Path.home() / ".hiringfunnel"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

# Maps AI provider name → environment variable that holds the API key.
# Shared with easyapplybot._llm_* methods which read from these env vars.
_PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


class SystemConfig(BaseModel):
    """System-level settings shared across all profiles."""

    ai_provider: str = "openai"  # "openai" | "anthropic" | "gemini" | "ollama"
    ai_api_key: str = ""


def load_settings() -> SystemConfig:
    """Load system config from disk. Returns defaults if file is missing or corrupt."""
    if not SETTINGS_FILE.exists():
        return SystemConfig()
    try:
        return SystemConfig(**json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, Exception) as exc:
        log.warning(f"settings.json unreadable ({exc}), using defaults")
        return SystemConfig()


def save_settings(settings: SystemConfig) -> None:
    """Write system config to disk."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        settings.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _inject_ai_env(settings: SystemConfig) -> None:
    """Inject AI provider config into os.environ for use by EasyApplyBot.

    - Sets the provider-specific API key env var only when non-empty (never
      overwrites an existing var with an empty string).
    - Sets HIRINGFUNNEL_AI_PROVIDER via setdefault so an existing env var or
      dotenv value takes precedence over settings.json.
    """
    if settings.ai_api_key:
        env_var = _PROVIDER_ENV.get(settings.ai_provider.lower())
        if env_var:
            os.environ[env_var] = settings.ai_api_key
    # setdefault: existing env (including .env) wins over settings.json
    os.environ.setdefault("HIRINGFUNNEL_AI_PROVIDER", settings.ai_provider)
    log.info(f"AI provider: {os.environ.get('HIRINGFUNNEL_AI_PROVIDER', settings.ai_provider)}")
