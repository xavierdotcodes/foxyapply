# TODOS

## TODO: Chrome session recovery after crash
Priority: P2 | Effort: M | Depends on: per-job try/except (shipped)

**What:** Detect when Chrome has crashed or the WebDriver connection is lost, restart the browser, re-authenticate to LinkedIn, and continue the job queue from where it left off.

**Why:** Per-job try/except now prevents one stuck form from killing the run, but a hard Chrome crash still terminates the entire session. Cron jobs scheduled overnight will silently produce zero applications if Chrome crashes at job #3 of 50.

**Current state:** `EasyApplyBot` constructs `self.browser` once in `__init__` and never recreates it. A `WebDriverException` (session not found, window closed, etc.) propagates up through `applications_loop()` and kills the whole run.

**Where to start:** Wrap `applications_loop()` in a retry loop that catches `WebDriverException`, calls a new `_restart_browser()` method (close, re-init, re-login), and resumes. Track restart count to avoid infinite loop (cap at 3).

**Depends on:** Per-job try/except is already shipped — this builds on top of it.

---

## TODO: Vision AI form filling (Phase 2)
Priority: P3 | Effort: L | Depends on: LLM radio fallback (shipped)

**What:** Screenshot the current form panel and pass the image to a vision-capable LLM (GPT-4o, Claude 3.5) to extract field labels, types, and suggested answers in one shot — replacing the brittle CSS selector + keyword matching approach.

**Why:** The current approach fails on non-standard LinkedIn form widgets (custom dropdowns, slider inputs, multi-select). Vision AI would handle any form layout without needing new selectors.

**Current state:** LLM is used as a text fallback only. `fill_invalids()` and `fill_up()` use fixed CSS selectors to locate fields and keyword matching to select answers.

**Where to start:** Add a `_fill_panel_via_vision()` method that screenshots `div[data-test-form-page]`, encodes it as base64, calls the LLM vision API, parses the JSON response (`{field_label: answer}`), and dispatches to existing fill helpers. Call it as a fallback when `fill_up()` returns without progress.

**Depends on:** LLM radio fallback (shipped). LLM provider config already exists.

---

## TODO: Timed-out counter in TUI status panel
Priority: P3 | Effort: S | Depends on: deadline watchdog (shipped)

**What:** Add a "Timed out" counter to the Rich live panel shown during a run, alongside the existing Applied / Failed counters.

**Why:** Right now timed-out jobs are silently counted as failures. Showing a separate counter helps the operator tune the 60-second deadline and identify problematic job boards.

**Current state:** `_emit("job_failed", {..., "error": "timeout"})` fires on timeout, but the TUI only shows `bot.applied_count` and `bot.failed_count`. There is no `bot.timeout_count` attribute.

**Where to start:** Add `self.timeout_count = 0` to `EasyApplyBot.__init__`. Increment it in the `except TimeoutError` block in `applications_loop()`. Update the Rich `Table` in `hiringfunnel.py`'s `run_profile_sequence()` to show a third "Timed out" column.

**Depends on:** Deadline watchdog is already shipped.

---

## TODO: Reduce load_page() sleep for headless runs
Priority: P3 | Effort: S | Depends on: --headless flag (shipped)

**What:** When running headless, halve (or remove) the fixed `time.sleep()` calls in `load_page()` and `next_jobs_page()` since there is no visible browser to stabilize and page loads are faster without rendering.

**Why:** Headless cron runs currently take just as long as interactive runs. A typical client run sleeps 3–5 seconds per page load; with 5 pages of results that's 15–25 seconds of pure sleep per keyword.

**Current state:** `load_page()` calls `time.sleep(self.delay)` where `self.delay` is configured per-profile. `HIRINGFUNNEL_HEADLESS` env var is already set before `EasyApplyBot` is constructed.

**Where to start:** In `EasyApplyBot.__init__`, after `self.delay` is set, add: `if os.environ.get("HIRINGFUNNEL_HEADLESS") == "1": self.delay = max(1, self.delay // 2)`. Consider making the divisor configurable later.

**Depends on:** `--headless` flag and `HIRINGFUNNEL_HEADLESS` env var are already shipped.
