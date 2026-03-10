"""Debug runner: runs all saved profiles in sequence (starting from index 0) without the TUI."""
from profiles import list_names, load_profiles
from hiringfunnel import run_profile_sequence

names = list_names()
if not names:
    print("No profiles found in ~/.hiringfunnel/profiles.json")
    raise SystemExit(1)

profiles = load_profiles()
print(f"Starting with profile: {names[0]!r}  ({len(names)} profile(s) available)")
run_profile_sequence(names[0], names, profiles)
