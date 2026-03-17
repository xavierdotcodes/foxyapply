"""LinkedIn adapter — delegates to the existing EasyApplyBot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

from .base import JobBoardBot

if TYPE_CHECKING:
    from easyapplybot import ProfileConfig


class LinkedInBot(JobBoardBot):
    """Thin wrapper around EasyApplyBot.

    EasyApplyBot already handles login, Easy Apply form-filling, daily limit
    detection, and all on_event callbacks.  This class satisfies the
    JobBoardBot interface so it slots into the multi-board orchestrator.
    """

    name = "linkedin"
    display_name = "LinkedIn"

    def __init__(
        self,
        config: "ProfileConfig",
        on_event: Optional[Callable] = None,
        blacklist: Optional[List[str]] = None,
        blacklist_titles: Optional[List[str]] = None,
    ) -> None:
        super().__init__(config, on_event, blacklist=blacklist, blacklist_titles=blacklist_titles)
        # _bot is created lazily inside run() so that Chrome doesn't launch
        # until this board is actually about to run.
        self._bot = None

    def run(self, positions: List[str], locations: List[str]) -> None:
        # Import here to avoid circular imports at module load time
        from easyapplybot import EasyApplyBot

        self._bot = EasyApplyBot(
            self.config, on_event=self._on_event,
            blacklist=self.blacklist, blacklist_titles=self.blacklist_titles,
        )

        if not self._bot.start_linkedin(self.config.email, self.config.password):
            # EasyApplyBot already emitted login_failed via on_event
            return

        # May raise DailyLimitReachedException — orchestrator handles it
        self._bot.start_apply(positions, locations)

    def stop(self) -> None:
        super().stop()
        if self._bot is not None:
            self._bot.stop()

    def close(self) -> None:
        if self._bot is not None:
            try:
                self._bot.close()
            except Exception:
                pass
            self._bot = None
