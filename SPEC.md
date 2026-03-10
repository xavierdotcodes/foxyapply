# HiringFunnel – Living Spec

## Overview

HiringFunnel is a LinkedIn Easy Apply bot with a terminal UI for profile management. It is a single Python package with no Go, no frontend, and no build infrastructure.

**Entry point:** `python hiringfunnel.py` (or `hiringfunnel` after install)

---

## Install

### Method 1 – Direct (dev/no-install)
```bash
pip install -r requirements.txt
python hiringfunnel.py
```

### Method 2 – Local install
```bash
pip install .
hiringfunnel
```

### Method 3 – From GitHub
```bash
pip install git+https://github.com/pypesdev/hiring-funnel
hiringfunnel
```

---

## Data Model

Profiles are stored in `~/.hiringfunnel/profiles.json` as:
```json
{
  "Profile Name": {
    "email": "user@example.com",
    "password": "linkedin_password",
    "phone_number": "555-1234",
    "positions": ["Software Engineer", "Backend Developer"],
    "locations": ["New York", "Remote"],
    "remote_only": false,
    "profile_url": "https://linkedin.com/in/username",
    "user_city": "New York",
    "user_state": "NY",
    "zip_code": "10001",
    "years_experience": 5,
    "desired_salary": 120000,
    "openai_api_key": "sk-...",
    "blacklist": ["CompanyToSkip"],
    "blacklist_titles": ["intern", "junior"]
  }
}
```

These fields map 1:1 to `ProfileConfig` in `easyapplybot.py` (Pydantic model).

---

## TUI Flow

### Main Menu
```
? What would you like to do?
  ❯ Run: "John Doe"
    Run: "Jane Smith"
    ──────────────────
    Create new profile
    Edit a profile
    Delete a profile
    Quit
```

### Create / Edit Profile
questionary prompts for each field in order:
- Email address
- LinkedIn password (hidden input)
- Phone number
- Job positions (comma-separated)
- Locations to search (comma-separated)
- Remote only? (y/n)
- LinkedIn profile URL
- City, State, ZIP code
- Years of experience
- Desired salary
- OpenAI API key (optional)
- Blacklisted companies (comma-separated)
- Blacklisted job titles (comma-separated)

### Run Profile
Starts bot in a background thread. Shows live panel:
```
╭─ HiringFunnel ──────────────────────╮
│ Profile: John Doe                   │
│ Applied: 12  Failed: 1  Seen: 45    │
│ Status: Applying to Software Eng... │
│                                     │
│   Applied: Backend Engineer @ Acme  │
│   Failed: Intern @ StartupXYZ       │
╰─────────────────────────────────────╯
Press Ctrl+C to stop.
```
Ctrl+C signals stop, joins thread, exits cleanly.

---

## Bot Interface

`EasyApplyBot.__init__(config: ProfileConfig, on_event: Optional[Callable[[str, dict], None]] = None)`

The `on_event` callback is called synchronously from the bot thread with:
- `("login_success", {})`
- `("login_failed", {"error": "..."})`
- `("bot_started", {})`
- `("bot_stopped", {"reason": "..."})`
- `("job_applying", {"job_id": "...", "title": "...", "company": "..."})`
- `("job_applied", {"job_id": "...", "title": "...", "company": "..."})`
- `("job_failed", {"job_id": "...", "title": "...", "error": "..."})`
- `("progress", {"applied": N, "failed": N, "total_seen": N})`
- `("daily_limit_reached", {"profile_email": "..."})` — LinkedIn's daily Easy Apply limit detected; bot stops and TUI rotates to next profile
- `("error", {"message": "..."})`

`_run_bot(config, on_event=None)` is the thread target. Creates the bot, logs in, starts applying.

When `daily_limit_reached` fires, `run_profile_sequence` in `hiringfunnel.py` automatically continues with the next profile (sorted order, starting after the current one). If no profiles remain, the session ends.

---

## File Layout

```
hiringfunnel.py    # TUI entry point (questionary + rich)
easyapplybot.py    # Bot logic (ProfileConfig, EasyApplyBot, _run_bot)
profiles.py        # JSON profile CRUD (~/.hiringfunnel/profiles.json)
pyproject.toml     # Package definition for pip install / pipx
requirements.txt   # Flat dep list (alternative install)
SPEC.md            # This file
output.csv         # Applied jobs log (auto-created by bot)
tests/
  __init__.py
  test_bot.py      # Bot logic tests
  test_profiles.py # Profile storage tests
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| selenium | Browser automation |
| beautifulsoup4 + lxml | HTML parsing |
| fake-useragent | Random user agent |
| openai | LLM field-fill fallback |
| python-dotenv | .env support |
| pydantic | ProfileConfig model |
| requests | API ping on apply |
| questionary | TUI prompts |
| rich | Live status panel |
| pyautogui | Mouse jiggle (optional) |

---

## Testing

```bash
pytest tests/
```

Tests run without Selenium, Chrome, or network access. Bot logic is tested via method binding stubs. Profile storage uses `tmp_path` fixtures with patched file paths.
