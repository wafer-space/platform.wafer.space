"""
Browser test configuration and fixtures.
"""

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager


def pytest_addoption(parser):
    """Add command-line options for browser testing."""
    parser.addoption(
        "--browser",
        action="store",
        default="chrome",
        help="Browser to use for testing (chrome, firefox)",
        choices=["chrome", "firefox"],
    )
    parser.addoption(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser tests in headless mode",
    )
    parser.addoption(
        "--window-size",
        action="store",
        default="1920,1080",
        help="Browser window size (default: 1920,1080)",
    )


@pytest.fixture(scope="session")
def browser_config(request):
    """Get browser configuration from command-line options."""
    return {
        "browser": request.config.getoption("--browser"),
        "headless": request.config.getoption("--headless"),
        "window_size": request.config.getoption("--window-size"),
    }


@pytest.fixture
def chrome_options(browser_config):
    """Configure Chrome options."""
    options = ChromeOptions()

    # Set window size
    width, height = browser_config["window_size"].split(",")
    options.add_argument(f"--window-size={width},{height}")

    # Headless mode
    if browser_config["headless"]:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

    # Other useful options
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)  # noqa: FBT003

    # Suppress console logs
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    return options


@pytest.fixture
def firefox_options(browser_config):
    """Configure Firefox options."""
    options = FirefoxOptions()

    # Set window size
    width, height = browser_config["window_size"].split(",")
    options.add_argument(f"--width={width}")
    options.add_argument(f"--height={height}")

    # Headless mode
    if browser_config["headless"]:
        options.add_argument("--headless")

    # Other useful options
    options.set_preference("dom.webdriver.enabled", False)  # noqa: FBT003
    options.set_preference("useAutomationExtension", False)  # noqa: FBT003

    return options


@pytest.fixture
def driver(browser_config, chrome_options, firefox_options):
    """Create WebDriver instance based on browser configuration."""
    browser = browser_config["browser"]

    if browser == "chrome":
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    elif browser == "firefox":
        service = FirefoxService(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=firefox_options)
    else:
        raise ValueError(f"Unsupported browser: {browser}")

    # Set implicit wait
    driver.implicitly_wait(10)

    # Maximize window if not headless
    if not browser_config["headless"]:
        driver.maximize_window()

    yield driver

    # Cleanup
    driver.quit()


@pytest.fixture
def live_server_url(live_server):
    """Get the URL of the Django live test server."""
    return live_server.url


@pytest.fixture
def authenticated_driver(driver, live_server_url, django_user_model):
    """Create a driver with an authenticated user session."""
    # Create a test user
    user = django_user_model.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )

    # Navigate to login page
    driver.get(f"{live_server_url}/accounts/login/")

    # Find and fill login form
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.wait import WebDriverWait

    # Wait for login form to be present
    wait = WebDriverWait(driver, 10)

    # Fill in credentials
    username_field = wait.until(
        EC.presence_of_element_located((By.NAME, "login")),
    )
    username_field.send_keys("testuser")

    password_field = driver.find_element(By.NAME, "password")
    password_field.send_keys("testpass123")

    # Submit form
    submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
    submit_button.click()

    # Wait for redirect after successful login
    wait.until(
        EC.url_changes(f"{live_server_url}/accounts/login/"),
    )

    return driver


@pytest.fixture(autouse=True)
def _screenshot_on_failure(request, driver):
    """Capture screenshot on test failure."""
    yield

    # Check if test failed
    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        # Create screenshots directory if it doesn't exist
        screenshots_dir = "tests/browser/screenshots"
        from pathlib import Path
        screenshots_path = Path(screenshots_dir)
        screenshots_path.mkdir(parents=True, exist_ok=True)

        # Generate screenshot filename
        test_name = request.node.name.replace("[", "_").replace("]", "_")
        screenshot_path = screenshots_path / f"failure_{test_name}.png"

        # Take screenshot
        driver.save_screenshot(screenshot_path)
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Screenshot saved: %s", screenshot_path)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Make test result available to fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


@pytest.fixture
def wait(driver):
    """Create a WebDriverWait instance."""
    return WebDriverWait(driver, 10)


@pytest.fixture
def take_screenshot(driver):
    """Helper function to take screenshots during tests."""
    def _take_screenshot(name):
        from pathlib import Path
        screenshots_path = Path("tests/browser/screenshots")
        screenshots_path.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshots_path / f"{name}.png"
        driver.save_screenshot(str(screenshot_path))
        return str(screenshot_path)

    return _take_screenshot
