import logging
import os
import random
import re
import threading
import time
from typing import Callable, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, model_validator

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore[assignment]

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None  # type: ignore[assignment]

try:
    import google.generativeai as _genai
except ImportError:
    _genai = None  # type: ignore[assignment]

try:
    import ollama as _ollama
except ImportError:
    _ollama = None  # type: ignore[assignment]

from fake_useragent import UserAgent
import requests
from openai import OpenAI
from dotenv import load_dotenv

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class DailyLimitReachedException(Exception):
    """Raised when LinkedIn's daily Easy Apply submission limit is detected on page."""
    pass


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class ProfileConfig(BaseModel):
    email: str
    password: str
    phone_number: str = ""
    positions: List[str] = []
    locations: List[str] = []
    remote_only: bool = False
    profile_url: str = ""
    user_city: str = ""
    user_state: str = ""
    zip_code: str = ""
    years_experience: int = 0
    desired_salary: int = 0
    ai_provider: str = "openai"   # "openai" | "anthropic" | "gemini" | "ollama"
    ai_api_key: str = ""
    blacklist: List[str] = []
    blacklist_titles: List[str] = []

    @model_validator(mode='before')
    @classmethod
    def _migrate_legacy(cls, data):
        if isinstance(data, dict) and 'openai_api_key' in data and 'ai_api_key' not in data:
            data['ai_api_key'] = data.pop('openai_api_key')
            data.setdefault('ai_provider', 'openai')
        return data


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

def setup_logger() -> None:
    log_dir = os.path.join('.', 'logs')
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s',
        datefmt='%d-%b-%y %H:%M:%S',
    )
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        c_handler = logging.StreamHandler()
        c_handler.setLevel(logging.DEBUG)
        c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
        c_handler.setFormatter(c_format)
        log.addHandler(c_handler)


# ---------------------------------------------------------------------------
# EasyApplyBot
# ---------------------------------------------------------------------------

class EasyApplyBot:
    MAX_SEARCH_TIME = 20 * 60 * 60

    def __init__(self, config: ProfileConfig, on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        setup_logger()

        self._on_event = on_event

        _PROVIDER_ENV = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
        }
        if config.ai_api_key:
            env_var = _PROVIDER_ENV.get(config.ai_provider.lower())
            if env_var:
                os.environ[env_var] = config.ai_api_key
        else:
            load_dotenv()

        if config.ai_provider.lower() != "ollama" and not os.environ.get(
            _PROVIDER_ENV.get(config.ai_provider.lower(), "")
        ):
            log.warning("AI API key not set – LLM fallback will be disabled")

        log.info("Welcome to Easy Apply Bot")

        self._stop_event = threading.Event()
        self.applied_count = 0
        self.failed_count = 0
        self.total_seen = 0

        self.config = config
        self.phone_number = config.phone_number
        self.location = f"{config.user_city}, {config.user_state}" if config.user_city else ""
        self.years_of_experience = str(config.years_experience) if config.years_experience else ""
        self.desired_salary = str(config.desired_salary) if config.desired_salary else ""
        self.linkedin_profile_url = config.profile_url
        self.zip_code = config.zip_code
        self.user_state = config.user_state
        self.checked_invalid = False
        self.blacklist = [c.lower() for c in config.blacklist]
        self.blacklist_titles = [t.lower() for t in config.blacklist_titles]

        # Setup Selenium driver
        self.browser = self._create_driver()
        self.wait = WebDriverWait(self.browser, 30)

    def _emit(self, event_type: str, data: Optional[dict] = None) -> None:
        """Call the on_event callback if set."""
        if self._on_event is not None:
            try:
                self._on_event(event_type, data or {})
            except Exception as e:
                log.debug(f"on_event callback error: {e}")

    def _check_daily_limit(self) -> bool:
        """Return True if LinkedIn's daily submission limit notice is present."""
        try:
            elements = self.browser.find_elements(By.CLASS_NAME, "artdeco-inline-feedback__message")
            return any("limit daily submissions" in el.text.lower() for el in elements)
        except Exception:
            return False

    def _create_driver(self):
        ua = UserAgent()
        user_agent = ua.random
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features")
        options.add_argument(f'--user-agent={user_agent}')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        return webdriver.Chrome(options=options)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()

    def close(self):
        try:
            self.browser.quit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # LinkedIn login
    # ------------------------------------------------------------------

    def start_linkedin(self, username, password) -> bool:
        log.info("Logging in.....Please wait :)")
        self.browser.get("https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin")
        try:
            user_field = self.browser.find_element("id", "username")
            pw_field = self.browser.find_element("id", "password")
            login_button = self.browser.find_element(By.CLASS_NAME, "btn__primary--large")
            user_field.send_keys(username)
            user_field.send_keys(Keys.TAB)
            time.sleep(2)
            pw_field.send_keys(password)
            time.sleep(2)
            login_button.click()
            time.sleep(3)
            self._emit("login_success")
            return True
        except TimeoutException:
            log.info("TimeoutException! Username/password field or login button not found")
            self._emit("login_failed", {"error": "Timeout finding login fields"})
            return False
        except Exception as e:
            self._emit("login_failed", {"error": str(e)})
            return False

    # ------------------------------------------------------------------
    # Main apply loop
    # ------------------------------------------------------------------

    def fill_data(self) -> None:
        try:
            self.browser.set_window_size(1, 1)
            self.browser.set_window_position(2000, 2000)
        except Exception as e:
            log.info(f"Could not set window size/position: {e}")

    def start_apply(self, positions, locations) -> None:
        self.fill_data()

        combos = []
        while len(combos) < len(positions) * len(locations):
            if self.stopped:
                return
            position = positions[random.randint(0, len(positions) - 1)]
            location = locations[random.randint(0, len(locations) - 1)]
            combo = (position, location)
            if combo not in combos:
                combos.append(combo)
                log.info(f"Applying to {position}: {location}")
                location_param = "&location=" + location
                self.applications_loop(position, location_param)
            if len(combos) > 500:
                break

    def applications_loop(self, position, location):
        count_application = 0
        count_job = 0
        jobs_per_page = 0
        start_time = time.time()

        log.info("Looking for jobs.. Please wait..")
        try:
            self.browser.set_window_position(1, 1)
            self.browser.maximize_window()
        except Exception as e:
            log.info(f"Could not set window size/position: {e}")

        self.browser, _ = self.next_jobs_page(position, location, jobs_per_page)
        log.info("Looking for jobs.. Please wait..")

        while time.time() - start_time < self.MAX_SEARCH_TIME:
            if self.stopped:
                return

            try:
                log.info(f"{(self.MAX_SEARCH_TIME - (time.time() - start_time)) // 60} minutes left in this search")

                self.load_page()
                links = self.browser.find_elements("xpath", '//div[@data-job-id]')
                if len(links) == 0:
                    log.debug("No links found")
                    break

                IDs = []
                for link in links:
                    children = link.find_elements("xpath", './/a[contains(@class, "job-card-container__link")]')
                    for child in children:
                        href = child.get_attribute("href")
                        if href:
                            parsed_url = urlparse(href)
                            job_id = parsed_url.path.split('/')[-2]
                            if job_id:
                                try:
                                    IDs.append(int(job_id))
                                except ValueError:
                                    pass
                jobIDs = set(IDs)
                self.total_seen += len(jobIDs)

                if len(jobIDs) == 0 and len(IDs) > 23:
                    jobs_per_page += 25
                    count_job = 0
                    self.avoid_lock()
                    self.browser, jobs_per_page = self.next_jobs_page(position, location, jobs_per_page)

                for i, jobID in enumerate(jobIDs):
                    if self.stopped:
                        return

                    count_job += 1
                    self.get_job_page(jobID)

                    # Extract title/company for events
                    try:
                        title_parts = self.browser.title.split(' | ')
                        job_title = re.search(r"\(?\d?\)?\s?(\w.*)", title_parts[0])
                        job_title = job_title.group(1) if job_title else title_parts[0]
                        company = re.search(r"(\w.*)", title_parts[1]) if len(title_parts) > 1 else None
                        company = company.group(1) if company else "Unknown"
                    except Exception:
                        job_title = "Unknown"
                        company = "Unknown"

                    # Check blacklists
                    if self.blacklist and company.lower() in self.blacklist:
                        log.info(f"Skipping blacklisted company: {company}")
                        continue
                    if self.blacklist_titles and any(bt in job_title.lower() for bt in self.blacklist_titles):
                        log.info(f"Skipping blacklisted title: {job_title}")
                        continue

                    self._emit("job_applying", {"job_id": str(jobID), "title": job_title, "company": company})

                    button = self.get_easy_apply_button()

                    if button is not False:
                        log.info("Clicking the EASY apply button")
                        time.sleep(3)
                        result = self.send_resume()
                        count_application += 1
                        if result:
                            self.applied_count += 1
                            self._emit("job_applied", {"job_id": str(jobID), "title": job_title, "company": company})
                        else:
                            self.failed_count += 1
                            self._emit("job_failed", {"job_id": str(jobID), "title": job_title, "error": "submit failed"})
                    else:
                        log.info("The button does not exist.")
                        result = False

                    self._emit("progress", {
                        "applied": self.applied_count,
                        "failed": self.failed_count,
                        "total_seen": self.total_seen,
                    })

                    if count_application != 0 and count_application % 20 == 0:
                        sleepTime = random.randint(100, 300)
                        log.info(f"Time for a nap - see you in: {int(sleepTime / 60)} min")
                        time.sleep(sleepTime)

                    if count_job == len(jobIDs):
                        jobs_per_page += 25
                        count_job = 0
                        log.info("Going to next jobs page")
                        self.avoid_lock()
                        self.browser, jobs_per_page = self.next_jobs_page(position, location, jobs_per_page)

            except DailyLimitReachedException:
                raise
            except Exception as e:
                log.error(f"Exception in main application loop: {e}")
                self._emit("error", {"message": str(e)})

    # ------------------------------------------------------------------
    # Page / job helpers
    # ------------------------------------------------------------------

    def write_to_file(self, button, jobID, browserTitle, result) -> None:
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

    def get_job_page(self, jobID):
        job = 'https://www.linkedin.com/jobs/view/' + str(jobID)
        self.browser.get(job)
        self.job_page = self.load_page()
        return self.job_page

    def get_easy_apply_button(self):
        if self._check_daily_limit():
            log.info("Daily application limit detected before button check")
            raise DailyLimitReachedException("Daily application limit reached")
        try:
            button = self.browser.find_elements("xpath", '//*[contains(@aria-label, "Easy Apply to") or contains(@aria-label, "LinkedIn Apply to")]')
            if len(button) == 0:
                return False

            javascript = """
            let elements = Array.from(document.querySelectorAll('button[aria-label]'));
            let targetElement = elements.find(el => el.getAttribute('aria-label').includes('Easy Apply to') || el.getAttribute('aria-label').includes('LinkedIn Apply to'));
            if (targetElement) {
                targetElement.click();
            }
            """
            self.browser.execute_script(javascript)
            time.sleep(1)

            if self._check_daily_limit():
                log.info("Daily application limit detected after button click")
                raise DailyLimitReachedException("Daily application limit reached")

            return True
        except DailyLimitReachedException:
            raise
        except Exception as e:
            log.error(f"exception in get_easy_apply_button: {e}")
            return False

    def wait_for_loader_to_disappear(self, timeout=10):
        try:
            WebDriverWait(self.browser, timeout).until(
                EC.invisibility_of_element_located((By.CLASS_NAME, "jobs-loader"))
            )
        except Exception:
            pass
        time.sleep(0.5)

    def fill_out_phone_number(self):
        def is_present(button_locator) -> bool:
            return len(self.browser.find_elements(button_locator[0], button_locator[1])) > 0

        try:
            next_locater = (By.CSS_SELECTOR, "button[aria-label='Continue to next step']")
            input_field = self.browser.find_element("xpath", "//input[contains(@id,'phoneNumber')]")
            if input_field:
                input_field.clear()
                input_field.send_keys(self.phone_number)
                time.sleep(random.uniform(4.5, 6.5))

                next_locater = (By.CSS_SELECTOR, "button[aria-label='Continue to next step']")
                error_locator = (By.CLASS_NAME, "artdeco-inline-feedback__message")

                button = None
                if is_present(next_locater):
                    button = self.wait.until(EC.element_to_be_clickable(next_locater))

                if is_present(error_locator):
                    for element in self.browser.find_elements(error_locator[0], error_locator[1]):
                        text = element.text
                        if "Please enter" in text:
                            button = None
                            break
                if button:
                    button.click()
                    time.sleep(random.uniform(1.5, 2.5))
        except Exception:
            log.debug("Could not find phone number field")

    def send_resume(self) -> bool:
        def is_present(button_locator) -> bool:
            return len(self.browser.find_elements(button_locator[0], button_locator[1])) > 0

        def has_errors() -> bool:
            return len(self.browser.find_elements(By.XPATH, '//*[contains(@type, "error-pebble-icon")]')) > 0

        try:
            time.sleep(random.uniform(1.5, 2.5))
            next_locater = (By.CSS_SELECTOR, "button[aria-label='Continue to next step']")
            review_locater = (By.CSS_SELECTOR, "button[aria-label='Review your application']")
            submit_locater = (By.CSS_SELECTOR, "button[aria-label='Submit application']")
            submit_application_locator = (By.CSS_SELECTOR, "button[aria-label='Submit application']")
            error_locator = (By.CLASS_NAME, "artdeco-inline-feedback__message")
            follow_locator = (By.CSS_SELECTOR, "label[for='follow-company-checkbox']")

            submitted = False
            while True:
                if self.stopped:
                    return False

                button = None
                buttons = [next_locater, review_locater, follow_locator,
                           submit_locater, submit_application_locator]
                for i, button_locator in enumerate(buttons):
                    if is_present(button_locator) and not has_errors():
                        button = self.wait.until(EC.element_to_be_clickable(button_locator))

                    if is_present(error_locator):
                        try:
                            for element in self.browser.find_elements(error_locator[0], error_locator[1]):
                                text = element.text
                                if ("Please enter" in text or "Please make" in text or "Enter a" in text or "Select checkbox to proceed") and not self.checked_invalid:
                                    self.fill_invalids()
                                    break
                        except Exception as e:
                            log.info(e)

                    if button:
                        button.click()
                        time.sleep(random.uniform(1.5, 2.5))
                        if i in (3, 4):
                            submitted = True
                        if i != 2:
                            break
                if submitted:
                    self.checked_invalid = False
                    log.info("Application Submitted")
                    try:
                        requests.get('https://api.pypes.dev/job-application')
                    except Exception as e:
                        log.info(f"{e} - cannot send job application to the api")
                    break

            time.sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            log.info(f"{e} - cannot apply to this job")
            raise e

        return submitted

    # ------------------------------------------------------------------
    # Field label / value helpers
    # ------------------------------------------------------------------

    def get_field_label(self, input_element):
        try:
            input_id = input_element.get_attribute('id')
            if input_id:
                label = self.browser.find_element(By.XPATH, f"//label[@for='{input_id}']")
                if label:
                    return label.text.strip()
            parent_label = input_element.find_element(By.XPATH, "./ancestor::label")
            if parent_label:
                return parent_label.text.strip()
            label_elements = self.browser.find_elements(By.XPATH, "//label")
            for label in label_elements:
                if label.is_displayed():
                    label_rect = label.rect
                    input_rect = input_element.rect
                    if (abs(label_rect['y'] - input_rect['y']) < 50 and
                            abs(label_rect['x'] - input_rect['x']) < 200):
                        return label.text.strip()
            placeholder = input_element.get_attribute('placeholder')
            if placeholder:
                return placeholder.strip()
            aria_label = input_element.get_attribute('aria-label')
            if aria_label:
                return aria_label.strip()
        except Exception as e:
            log.debug(f"Could not extract label for input: {e}")
        return ""

    def get_appropriate_value(self, label_text, input_type="text"):
        label_lower = label_text.lower()

        if any(keyword in label_lower for keyword in ['phone', 'mobile', 'telephone', 'contact']):
            return self.phone_number
        if 'city' in label_lower or 'location' in label_lower or 'reside' in label_lower:
            return self.location
        if 'have you ever worked' in label_lower:
            return 'No'
        if 'state' in label_lower:
            return self.user_state
        if 'zip' in label_lower or 'postal' in label_lower:
            return self.zip_code
        if any(keyword in label_lower for keyword in ['salary', 'wage', 'income']):
            return self.desired_salary
        if 'experience' in label_lower and 'years' in label_lower:
            return self.years_of_experience
        if 'available' in label_lower or 'start' in label_lower or 'notice' in label_lower:
            return '2 weeks'
        if any(keyword in label_lower for keyword in ['skill', 'technology', 'programming', 'language']):
            return 'Python, JavaScript, SQL'
        if any(keyword in label_lower for keyword in ['education', 'degree', 'university', 'college']):
            return 'Bachelor'
        if any(keyword in label_lower for keyword in ['linkedin', 'linked-in', 'linked in']):
            return self.linkedin_profile_url

        if input_type == "text":
            llm_answer = self.get_llm_suggested_answer(label_text, input_type)
            if llm_answer:
                return llm_answer
            return self.years_of_experience

        return ''

    def fill_invalids(self):
        try:
            location = self.browser.find_element(By.CSS_SELECTOR, "input[id*='GEO-LOCATION']")
        except Exception:
            location = None

        if location:
            location.send_keys(self.location)
            try:
                dropdown_option = WebDriverWait(self.browser, 10).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        "//div[contains(@class, 'basic-typeahead__selectable')]//span[contains(@class, 'search-typeahead-v2__hit-text')]"
                    ))
                )
                dropdown_option.click()
            except Exception:
                pass
            return

        try:
            your_name_label = self.browser.find_element(By.XPATH, "//label[contains(text(), 'Your Name')]")
            
        except Exception as e:
            your_name_label = None
            
        if your_name_label:
            input_id = your_name_label.get_attribute('for') if your_name_label else None
            input_element = self.browser.find_element(By.ID, input_id)
            input_element.clear()
            name = self.config.email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
            input_element.send_keys(name)

        text_inputs = self.browser.find_elements(By.XPATH, '//input[contains(@class, "fb-dash-form-element")]')
        for input_element in text_inputs:
            try:
                label_text = self.get_field_label(input_element)
                input_type = input_element.get_attribute('type') or 'text'
                appropriate_value = self.get_appropriate_value(label_text, input_type)
                if appropriate_value:
                    input_element.clear()
                    input_element.send_keys(appropriate_value)
                    log.info(f"Filled field '{label_text}' with value: {appropriate_value}")
                else:
                    input_element.clear()
                    input_element.send_keys('3')
                    log.info(f"Filled field '{label_text}' with default value: 3")
            except Exception as e:
                log.error(f"Error filling input field: {e}")
                try:
                    input_element.clear()
                    input_element.send_keys('3')
                except Exception:
                    pass

        time.sleep(1)

        radio_inputs = self.browser.find_elements(By.XPATH, '//input[@data-test-text-selectable-option__input="Yes"]')
        for input_element in radio_inputs:
            try:
                question_text = self.get_radio_question_text(input_element)
                question_lower = question_text.lower()
                if any(keyword in question_lower for keyword in ['visa', 'sponsor', 'work authorization', 'citizen']):
                    no_input = self.browser.find_element(By.XPATH, '//input[@data-test-text-selectable-option__input="No"]')
                    if no_input:
                        loc = no_input.location
                        element_to_click = self.browser.execute_script(
                            "return document.elementFromPoint(arguments[0], arguments[1]);",
                            loc['x'], loc['y'])
                        element_to_click.click()
                        log.info(f"Selected 'No' for visa-related question: {question_text}")
                        continue
                loc = input_element.location
                element_to_click = self.browser.execute_script(
                    "return document.elementFromPoint(arguments[0], arguments[1]);",
                    loc['x'], loc['y'])
                element_to_click.click()
                log.info(f"Selected 'Yes' for question: {question_text}")
            except Exception as e:
                log.error(f"Error handling radio button: {e}")
                try:
                    loc = input_element.location
                    element_to_click = self.browser.execute_script(
                        "return document.elementFromPoint(arguments[0], arguments[1]);",
                        loc['x'], loc['y'])
                    element_to_click.click()
                except Exception:
                    pass
        time.sleep(1)

        try:
            select_inputs = self.browser.find_elements(By.CSS_SELECTOR, 'select[aria-required="true"]')
            for inp in select_inputs:
                question_text = self.get_select_question_text(inp)
                question_lower = question_text.lower()
                select_obj = Select(inp)
                options = select_obj.options
                for option in options:
                    ot = option.text.lower()
                    if "united states" in ot:
                        select_obj.select_by_visible_text(option.text)
                        log.info(f"Selected option '{option.text}' for question: {question_text}")
                    elif "immediate family" in question_lower and "no" in ot:
                        select_obj.select_by_visible_text(option.text)
                        log.info(f"Selected option '{option.text}' for question: {question_text}")
                    elif "no" in ot and "require" in question_lower:
                        select_obj.select_by_visible_text(option.text)
                        log.info(f"Selected option '{option.text}' for question: {question_text}")
                    elif any(word in ot for word in ["confirm", "accept", "acknowledge"]):
                        select_obj.select_by_visible_text(option.text)
                        log.info(f"Selected option '{option.text}' for question: {question_text}")
                    elif ("yes" in ot and "do you require" not in question_lower) or "native" in ot or "U.S." in ot or "us" in ot or "linkedin" in ot or "united states" in ot or "citizen" in ot:
                        select_obj.select_by_visible_text(option.text)
                        log.info(f"Selected option '{option.text}' for question: {question_text}")
        except Exception as e:
            select_inputs = None

        text_area_inputs = self.browser.find_elements(By.XPATH, '//textarea[contains(@class, "fb-dash-form-element")]')
        for textarea in text_area_inputs:
            try:
                label_text = self.get_field_label(textarea)
                appropriate_value = self.get_appropriate_value(label_text, input_type="text")
                if appropriate_value:
                    textarea.clear()
                    textarea.send_keys(appropriate_value)
                    log.info(f"Filled textarea '{label_text}' with value: {appropriate_value}")
                else:
                    textarea.clear()
                    textarea.send_keys('3')
                    log.info(f"Filled textarea '{label_text}' with default value: 3")
            except Exception as e:
                log.error(f"Error filling textarea field: {e}")
                try:
                    textarea.clear()
                    textarea.send_keys('3')
                except Exception:
                    pass

    def load_page(self, sleep=.5):
        scroll_page = 0
        while scroll_page < 2000:
            self.browser.execute_script("window.scrollTo(0," + str(scroll_page) + " );")
            scroll_page += 500
            time.sleep(sleep)
        page = BeautifulSoup(self.browser.page_source, "lxml")
        return page

    def avoid_lock(self) -> None:
        if pyautogui is None:
            return
        try:
            pyautogui.FAILSAFE = False
            time.sleep(0.5)
            pyautogui.press('esc')
        except Exception as e:
            log.debug(f"avoid_lock skipped (no display?): {e}")

    def next_jobs_page(self, position, location, jobs_per_page):
        self.browser.get(
            "https://www.linkedin.com/jobs/search/?f_LF=f_AL&keywords=" +
            position + location + "&sortBy=DD&start=" + str(jobs_per_page))
        self.avoid_lock()
        self.load_page()
        return (self.browser, jobs_per_page)

    def finish_apply(self) -> None:
        self.browser.close()

    def get_radio_question_text(self, input_element):
        try:
            fieldset = input_element.find_element(By.XPATH, "./ancestor::fieldset[1]")
            return fieldset.accessible_name
        except Exception as e:
            log.debug(f"Could not extract radio question text: {e}")
        return ""

    def get_select_question_text(self, select_element):
        try:
            select_id = select_element.get_attribute('id')
            if select_id:
                label = self.browser.find_element(By.XPATH, f"//label[@for='{select_id}']")
                if label:
                    return label.text.strip()
            parent_label = select_element.find_element(By.XPATH, "./ancestor::label[1]")
            if parent_label:
                return parent_label.text.strip()
            label = select_element.find_element(By.XPATH, "preceding-sibling::label[1]")
            if label:
                return label.text.strip()
            aria_label = select_element.get_attribute('aria-label')
            if aria_label:
                return aria_label.strip()
        except Exception as e:
            log.debug(f"Could not extract select question text: {e}")
        return ""

    def _build_llm_prompt(self, label_text):
        name = self.config.email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
        positions_str = ', '.join(self.config.positions) if self.config.positions else "Software Engineer"
        location_str = self.location or "United States"
        yoe = self.years_of_experience or "3"
        salary = self.desired_salary or "100000"
        return (
            f"You are {name}, a professional applying for jobs as a {positions_str} "
            f"based in {location_str} with {yoe} years of experience. "
            f"Provide a short, succinct, professional answer for the following job application question: "
            f"'{label_text}'. If it so much as mentions numerics such as experience or hourly wage, "
            f"answer with ONLY a single numeric digit response and no additional text: {yoe} for years of experience, and {salary} for salary."
        )

    def _llm_openai(self, label_text):
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            return ""
        client = OpenAI(api_key=openai_api_key)
        prompt = self._build_llm_prompt(label_text)
        response = client.responses.create(
            model="gpt-4o",
            instructions=prompt,
            input=label_text,
        )
        return response.output_text.strip()

    def _llm_anthropic(self, label_text):
        if _anthropic is None:
            log.warning("anthropic package not installed – skipping LLM fallback")
            return ""
        prompt = self._build_llm_prompt(label_text)
        client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def _llm_gemini(self, label_text):
        if _genai is None:
            log.warning("google-generativeai package not installed – skipping LLM fallback")
            return ""
        prompt = self._build_llm_prompt(label_text)
        _genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        model = _genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text.strip()

    def _llm_ollama(self, label_text):
        if _ollama is None:
            log.warning("ollama package not installed – skipping LLM fallback")
            return ""
        prompt = self._build_llm_prompt(label_text)
        response = _ollama.chat(
            model="llama3.2",
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()

    def get_llm_suggested_answer(self, label_text, input_type="text"):
        provider = self.config.ai_provider.lower()
        try:
            if provider == "openai":
                answer = self._llm_openai(label_text)
            elif provider == "anthropic":
                answer = self._llm_anthropic(label_text)
            elif provider == "gemini":
                answer = self._llm_gemini(label_text)
            elif provider == "ollama":
                answer = self._llm_ollama(label_text)
            else:
                log.warning(f"Unknown AI provider '{provider}' – skipping LLM fallback")
                return ""
            if answer:
                log.info(f"LLM suggested answer for '{label_text}': {answer}")
            return answer
        except Exception as e:
            log.error(f"LLM request failed ({provider}): {e}")
        return ""


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------

_bot: Optional[EasyApplyBot] = None
_bot_thread: Optional[threading.Thread] = None
_bot_lock = threading.Lock()
_applying = False


def _run_bot(config: ProfileConfig, on_event: Optional[Callable[[str, dict], None]] = None):
    """Target function for the bot background thread."""
    global _bot, _applying
    try:
        _bot = EasyApplyBot(config, on_event=on_event)

        if not _bot.start_linkedin(config.email, config.password):
            if on_event:
                on_event("bot_stopped", {"reason": "login_failed"})
            _bot.close()
            _bot = None
            _applying = False
            return

        if on_event:
            on_event("bot_started", {})
        _applying = True

        positions = [p for p in config.positions if p]
        locations = [loc for loc in config.locations if loc]

        if not positions or not locations:
            if on_event:
                on_event("bot_stopped", {"reason": "no positions or locations configured"})
            _bot.close()
            _bot = None
            _applying = False
            return

        _bot.start_apply(positions, locations)
        if on_event:
            on_event("bot_stopped", {"reason": "completed"})
    except DailyLimitReachedException:
        log.info(f"Daily application limit reached for {config.email}")
        if on_event:
            on_event("daily_limit_reached", {"profile_email": config.email})
            on_event("bot_stopped", {"reason": "daily_limit_reached"})
    except Exception as e:
        log.error(f"Bot thread exception: {e}")
        if on_event:
            on_event("error", {"message": str(e)})
            on_event("bot_stopped", {"reason": f"error: {e}"})
    finally:
        if _bot:
            _bot.close()
            _bot = None
        _applying = False
