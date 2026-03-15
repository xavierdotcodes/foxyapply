"""Global test configuration.

Patches out all Chrome/WebDriver initialization so no real browser ever opens
during the test suite, regardless of which test file runs.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="session")
def block_chrome_globally():
    """Prevent any test from accidentally opening a real Chrome browser."""
    fake_driver = MagicMock()
    fake_driver.set_page_load_timeout = MagicMock()

    with patch("easyapplybot._make_chrome_driver", return_value=fake_driver), \
         patch("easyapplybot.webdriver.Chrome", return_value=fake_driver):
        yield
