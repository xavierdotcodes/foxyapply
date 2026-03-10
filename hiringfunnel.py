"""HiringFunnel – TUI entry point."""

import logging
import logging.handlers
import os
import threading
import time
from typing import Optional

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from db import get_all_stats, init_db, record_application
from easyapplybot import DailyLimitReachedException, EasyApplyBot, ProfileConfig, _run_bot
from profiles import delete_profile, list_names, load_profiles, upsert_profile

console = Console()

# Silence noisy third-party loggers at module level
for _noisy in ("selenium", "urllib3", "WDM"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Profile form
# ---------------------------------------------------------------------------

PROFILE_FIELDS = [
    ("email", "Email address", "text"),
    ("password", "LinkedIn password", "password"),
    ("phone_number", "Phone number", "text"),
    ("positions", "Job positions (comma-separated)", "text"),
    ("remote_only", "Remote only?", "confirm"),
    ("profile_url", "LinkedIn profile URL", "text"),
    ("user_city", "City", "text"),
    ("user_state", "State", "text"),
    ("zip_code", "ZIP code", "text"),
    ("years_experience", "Years of experience", "text"),
    ("desired_salary", "Desired salary", "text"),
    ("ai_provider", "AI provider", "select", ["openai", "anthropic", "gemini", "ollama"]),
    ("ai_api_key", "API key for selected provider (blank for Ollama)", "text"),
    ("blacklist", "Blacklisted companies (comma-separated)", "text"),
    ("blacklist_titles", "Blacklisted job titles (comma-separated)", "text"),
]


def _parse_list(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def prompt_profile(existing: Optional[dict] = None) -> Optional[dict]:
    """Prompt for all profile fields. Returns data dict or None if cancelled."""
    data = existing or {}
    answers = {}

    for field_def in PROFILE_FIELDS:
        field, label, kind = field_def[0], field_def[1], field_def[2]
        choices = field_def[3] if len(field_def) > 3 else None
        current = data.get(field, "")

        if kind == "select":
            default = current if current in choices else choices[0]
            result = questionary.select(label, choices=choices, default=default).ask()
            if result is None:
                return None
            answers[field] = result

        elif kind == "confirm":
            default = bool(current) if isinstance(current, bool) else False
            result = questionary.confirm(label, default=default).ask()
            if result is None:
                return None
            answers[field] = result

        elif kind == "password":
            result = questionary.password(label).ask()
            if result is None:
                return None
            answers[field] = result if result else current

        else:
            # Convert list fields back to comma-separated string for display
            if isinstance(current, list):
                current = ", ".join(current)
            elif isinstance(current, int):
                current = str(current) if current else ""

            result = questionary.text(label, default=str(current)).ask()
            if result is None:
                return None

            if field in ("positions", "blacklist", "blacklist_titles"):
                answers[field] = _parse_list(result)
            elif field in ("years_experience", "desired_salary"):
                answers[field] = _parse_int(result)
            else:
                answers[field] = result

    # Derive search locations from city/state
    city = answers.get("user_city", "").strip()
    state = answers.get("user_state", "").strip()
    if city and state:
        answers["locations"] = [f"{city}, {state}"]
    elif city:
        answers["locations"] = [city]
    elif state:
        answers["locations"] = [state]
    else:
        answers["locations"] = []

    return answers


# ---------------------------------------------------------------------------
# Run panel
# ---------------------------------------------------------------------------

class BotState:
    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        self.applied = 0
        self.failed = 0
        self.seen = 0
        self.status = "Starting..."
        self.log_lines: list = []
        self.stopped = False
        self.daily_limit_hit = False

    def on_event(self, event_type: str, data: dict) -> None:
        if event_type == "bot_started":
            self.status = "Applying to jobs..."
        elif event_type == "bot_stopped":
            reason = data.get("reason", "")
            self.status = f"Stopped: {reason}"
            self.stopped = True
        elif event_type == "login_success":
            self.status = "Logged in. Searching for jobs..."
        elif event_type == "login_failed":
            self.status = f"Login failed: {data.get('error', '')}"
            self.stopped = True
        elif event_type == "job_applying":
            title = data.get("title", "")
            company = data.get("company", "")
            self.status = f"Applying: {title} @ {company}"
            self.log_lines.append(f"  Applying: {title} @ {company}")
        elif event_type == "job_applied":
            title = data.get("title", "")
            company = data.get("company", "")
            self.applied += 1
            self.log_lines.append(f"  [green]Applied[/green]: {title}")
            try:
                record_application(self.profile_name, data.get("job_id", ""), title, company, "applied")
            except Exception:
                pass
        elif event_type == "job_failed":
            title = data.get("title", "")
            self.failed += 1
            self.log_lines.append(f"  [red]Failed[/red]: {title}")
            try:
                record_application(self.profile_name, data.get("job_id", ""), title, data.get("company", ""), "failed")
            except Exception:
                pass
        elif event_type == "progress":
            self.applied = data.get("applied", self.applied)
            self.failed = data.get("failed", self.failed)
            self.seen = data.get("total_seen", self.seen)
        elif event_type == "daily_limit_reached":
            self.daily_limit_hit = True
            email = data.get("profile_email", "this profile")
            self.status = f"Daily limit reached for {email}"
            self.log_lines.append(f"  [yellow]Daily limit reached[/yellow] for {email}")
        elif event_type == "error":
            msg = data.get("message", "")
            self.log_lines.append(f"  [red]Error[/red]: {msg}")

        # Keep log buffer trimmed
        if len(self.log_lines) > 20:
            self.log_lines = self.log_lines[-20:]

    def render(self) -> Panel:
        header = (
            f"Profile: [bold]{self.profile_name}[/bold]\n"
            f"Applied: [green]{self.applied}[/green]  "
            f"Failed: [red]{self.failed}[/red]  "
            f"Seen: {self.seen}\n"
            f"Status: {self.status}"
        )
        log_text = "\n".join(self.log_lines[-10:]) if self.log_lines else ""
        body = header + ("\n\n" + log_text if log_text else "")
        return Panel(body, title="[bold blue]HiringFunnel[/bold blue]", expand=False)


def _redirect_logs_to_file() -> None:
    """Route all log output to a file so nothing bleeds into the TUI."""
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/hiringfunnel.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s", "%H:%M:%S")
    )

    # Strip StreamHandlers from root so basicConfig() won't add another one
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    root.addHandler(file_handler)

    # Pre-populate the easyapplybot logger so setup_logger()'s
    # `if not log.handlers` guard skips adding a StreamHandler
    bot_log = logging.getLogger("easyapplybot")
    for h in list(bot_log.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            bot_log.removeHandler(h)
    bot_log.addHandler(file_handler)
    bot_log.setLevel(logging.DEBUG)
    bot_log.propagate = False


def run_profile_sequence(start_name: str, all_names: list, profiles: dict) -> None:
    """Run profiles in sequence, rotating to the next when daily limit is hit."""
    remaining = [n for n in all_names if n != start_name]
    names_to_try = [start_name] + remaining

    _redirect_logs_to_file()
    stop_all = threading.Event()

    for name in names_to_try:
        if stop_all.is_set():
            break

        data = profiles.get(name, {})
        try:
            config = ProfileConfig(**data)
        except Exception as e:
            console.print(f"[red]Invalid profile '{name}': {e}[/red]")
            continue

        state = BotState(name)
        bot_done = threading.Event()

        def bot_thread_fn(cfg=config, st=state, done=bot_done):
            _run_bot(cfg, on_event=st.on_event)
            done.set()

        thread = threading.Thread(target=bot_thread_fn, daemon=True)
        thread.start()

        console.print(f"\nRunning profile [bold]{name}[/bold]. Press [bold]Ctrl+C[/bold] to stop.\n")

        try:
            with Live(state.render(), refresh_per_second=2, console=console) as live:
                while not state.stopped and not bot_done.is_set():
                    live.update(state.render())
                    time.sleep(0.5)
                live.update(state.render())
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping bot...[/yellow]")
            from easyapplybot import _bot
            if _bot is not None:
                _bot.stop()
            thread.join(timeout=15)
            stop_all.set()
            break

        thread.join(timeout=15)

        if state.daily_limit_hit:
            idx = names_to_try.index(name) + 1
            if idx < len(names_to_try):
                console.print(f"[yellow]Switching to profile '{names_to_try[idx]}'...[/yellow]")
            else:
                console.print("[yellow]Daily limit reached. No more profiles to try.[/yellow]")
        else:
            break  # stopped cleanly — don't rotate

    console.print("[green]Bot stopped.[/green]")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def build_menu_choices(names: list, stats: dict = {}) -> list:
    choices = []
    for name in names:
        n_applied = stats.get(name, {}).get("applied", 0)
        choices.append(questionary.Choice(f'Run: "{name}"  (applied: {n_applied})', value=("run", name)))
    if names:
        choices.append(questionary.Separator())
    choices.append(questionary.Choice("Create new profile", value=("create", None)))
    choices.append(questionary.Choice("Edit a profile", value=("edit", None)))
    choices.append(questionary.Choice("Delete a profile", value=("delete", None)))
    choices.append(questionary.Choice("Quit", value=("quit", None)))
    return choices


def main() -> None:
    console.print("[bold blue]HiringFunnel[/bold blue] – LinkedIn Easy Apply Bot\n")

    init_db()

    while True:
        names = list_names()
        stats = get_all_stats()
        choices = build_menu_choices(names, stats)

        answer = questionary.select(
            "What would you like to do?",
            choices=choices,
        ).ask()

        if answer is None or answer == ("quit", None):
            console.print("Goodbye.")
            break

        action, target = answer

        if action == "run":
            profiles = load_profiles()
            run_profile_sequence(target, names, profiles)

        elif action == "create":
            name = questionary.text("Profile name:").ask()
            if not name:
                continue
            profiles = load_profiles()
            if name in profiles:
                console.print(f"[yellow]Profile '{name}' already exists. Use Edit to modify it.[/yellow]")
                continue
            data = prompt_profile()
            if data is None:
                continue
            upsert_profile(name, data)
            console.print(f"[green]Profile '{name}' created.[/green]")

        elif action == "edit":
            if not names:
                console.print("[yellow]No profiles to edit.[/yellow]")
                continue
            name = questionary.select(
                "Select profile to edit:",
                choices=names,
            ).ask()
            if not name:
                continue
            profiles = load_profiles()
            data = prompt_profile(existing=profiles.get(name, {}))
            if data is None:
                continue
            upsert_profile(name, data)
            console.print(f"[green]Profile '{name}' updated.[/green]")

        elif action == "delete":
            if not names:
                console.print("[yellow]No profiles to delete.[/yellow]")
                continue
            name = questionary.select(
                "Select profile to delete:",
                choices=names,
            ).ask()
            if not name:
                continue
            confirmed = questionary.confirm(f"Delete profile '{name}'?", default=False).ask()
            if confirmed:
                delete_profile(name)
                console.print(f"[green]Profile '{name}' deleted.[/green]")


if __name__ == "__main__":
    main()
