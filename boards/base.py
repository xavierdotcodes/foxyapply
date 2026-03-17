"""Abstract base class every job-board adapter must subclass."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, ClassVar, List, Optional

if TYPE_CHECKING:
    from easyapplybot import ProfileConfig


class JobBoardBot(ABC):
    """Base class for all job-board bots.

    Subclass contract
    -----------------
    - Set ``name``         — machine key used in ProfileConfig.job_boards, e.g. "indeed"
    - Set ``display_name`` — shown in the TUI,  e.g. "Indeed"
    - Implement ``run()``  — login + search + apply loop
    - Implement ``close()``— release the browser no matter what
    """

    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""

    def __init__(
        self,
        config: "ProfileConfig",
        on_event: Optional[Callable[[str, dict], None]] = None,
        blacklist: Optional[List[str]] = None,
        blacklist_titles: Optional[List[str]] = None,
    ) -> None:
        self.config = config
        self._on_event = on_event
        self._stop_event = threading.Event()
        self.applied_count = 0
        self.failed_count = 0
        self.blacklist: List[str] = blacklist or []
        self.blacklist_titles: List[str] = blacklist_titles or []

    # ------------------------------------------------------------------
    # Stop control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the bot to halt at the next safe checkpoint."""
        self._stop_event.set()

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: Optional[dict] = None) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event_type, data or {})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Interface — must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, positions: List[str], locations: List[str]) -> None:
        """Login, search, and apply.  Called by the orchestrator.

        Raise ``DailyLimitReachedException`` if the board's daily cap is hit.
        Raise ``NotImplementedError`` if the scaffold is not yet filled in.
        Any other exception is caught and logged by the orchestrator.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release the browser/driver.  Always called, even after errors."""
        ...
