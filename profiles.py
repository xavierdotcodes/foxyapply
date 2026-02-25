import json
from pathlib import Path
from typing import Optional

PROFILES_DIR = Path.home() / ".hiringfunnel"
PROFILES_FILE = PROFILES_DIR / "profiles.json"


def load_profiles() -> dict:
    """Load all profiles from disk. Returns {name: profile_data}."""
    if not PROFILES_FILE.exists():
        return {}
    try:
        return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_profiles(profiles: dict) -> None:
    """Write all profiles to disk."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(
        json.dumps(profiles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def upsert_profile(name: str, data: dict) -> None:
    """Create or update a profile by name."""
    profiles = load_profiles()
    profiles[name] = data
    save_profiles(profiles)


def delete_profile(name: str) -> bool:
    """Delete a profile by name. Returns True if it existed."""
    profiles = load_profiles()
    if name not in profiles:
        return False
    del profiles[name]
    save_profiles(profiles)
    return True


def list_names() -> list:
    """Return sorted list of profile names."""
    return sorted(load_profiles().keys())
