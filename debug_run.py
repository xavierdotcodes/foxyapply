"""Debug runner: runs the first saved profile without the TUI."""
from profiles import list_names, load_profiles
from easyapplybot import ProfileConfig, _run_bot

names = list_names()
if not names:
    print("No profiles found in ~/.hiringfunnel/profiles.json")
    raise SystemExit(1)

name = names[0]
config = ProfileConfig(**load_profiles()[name])
print(f"Running profile: {name!r}")
_run_bot(config)
