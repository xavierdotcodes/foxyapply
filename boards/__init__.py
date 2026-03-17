"""Job-board registry and multi-board orchestrator.

To add a new board:
  1. Create boards/<name>.py  subclassing JobBoardBot
  2. Import it in _load_registry() below and add it to the dict
  3. Add the name string to AVAILABLE_BOARDS
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Type

from .base import JobBoardBot

if TYPE_CHECKING:
    from easyapplybot import ProfileConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _load_registry() -> Dict[str, Type[JobBoardBot]]:
    from .linkedin import LinkedInBot
    from .indeed import IndeedBot
    return {
        LinkedInBot.name: LinkedInBot,
        IndeedBot.name: IndeedBot,
    }


# Populated on first call to get_registry() to avoid import-time side effects
_REGISTRY: Dict[str, Type[JobBoardBot]] = {}


def get_registry() -> Dict[str, Type[JobBoardBot]]:
    global _REGISTRY
    if not _REGISTRY:
        _REGISTRY = _load_registry()
    return _REGISTRY


# Human-readable ordered list shown in the TUI checkbox picker
AVAILABLE_BOARDS: List[str] = ["linkedin"]


# ---------------------------------------------------------------------------
# Stop signal
# ---------------------------------------------------------------------------

_current_bot: Optional[JobBoardBot] = None


def stop_current() -> None:
    """Signal the currently running board bot to stop."""
    global _current_bot
    if _current_bot is not None:
        _current_bot.stop()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_profile_all_boards(
    config: "ProfileConfig",
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> None:
    """Run every enabled job board for *config* in order.

    Flow per profile:
        linkedin  →  indeed  →  [more boards]  →  emit bot_stopped

    Daily-limit exceptions are caught per-board so subsequent boards
    still run.  NotImplementedError (scaffold not filled in) is surfaced
    as a visible error event rather than silently swallowed.
    """
    global _current_bot
    from easyapplybot import DailyLimitReachedException
    from settings import _inject_ai_env, load_settings

    # Load system settings (blacklist, AI provider, etc.) and inject env vars
    settings = load_settings()
    _inject_ai_env(settings)

    def emit(event_type: str, data: dict = {}) -> None:
        if on_event:
            try:
                on_event(event_type, data)
            except Exception:
                pass

    registry = get_registry()
    boards = [b for b in config.job_boards if b in registry]

    if not boards:
        emit("error", {"message": "No valid job boards configured."})
        emit("bot_stopped", {"reason": "no boards"})
        return

    positions = [p for p in config.positions if p]
    locations = [loc for loc in config.locations if loc]

    if not positions or not locations:
        emit("bot_stopped", {"reason": "no positions or locations configured"})
        return

    for board_name in boards:
        BotClass = registry[board_name]
        bot = BotClass(
            config, on_event=on_event,
            blacklist=settings.blacklist,
            blacklist_titles=settings.blacklist_titles,
        )
        _current_bot = bot

        emit("board_started", {"board": board_name, "display": BotClass.display_name})
        try:
            bot.run(positions, locations)
            emit("board_finished", {
                "board": board_name,
                "display": BotClass.display_name,
                "result": "completed",
            })

        except DailyLimitReachedException:
            log.info(f"Daily limit reached on {board_name} for {config.email}")
            emit("board_finished", {
                "board": board_name,
                "display": BotClass.display_name,
                "result": "daily_limit",
            })
            emit("daily_limit_reached", {"profile_email": config.email, "board": board_name})

        except NotImplementedError as e:
            log.warning(f"{board_name} scaffold not implemented: {e}")
            emit("board_finished", {
                "board": board_name,
                "display": BotClass.display_name,
                "result": "not_implemented",
            })
            emit("error", {
                "message": (
                    f"{BotClass.display_name} is not yet implemented. "
                    f"Open boards/{board_name}.py and fill in the TODOs."
                )
            })

        except Exception as e:
            log.error(f"{board_name} error: {e}")
            emit("board_finished", {
                "board": board_name,
                "display": BotClass.display_name,
                "result": "error",
            })
            emit("error", {"message": f"{BotClass.display_name}: {e}"})

        finally:
            try:
                bot.close()
            except Exception:
                pass

    _current_bot = None
    emit("bot_stopped", {"reason": "all boards completed"})
