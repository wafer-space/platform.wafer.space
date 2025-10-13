"""
Browser test configuration and fixtures.
"""

import contextlib
import logging
import os
import tempfile
from pathlib import Path

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.db import connection
from django.db import connections
from django.db import transaction
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

# ============================================================================
# CRITICAL: Block display for all browser tests by default
# This prevents accidental GUI browser windows in automated testing
# Display is only restored if --visible flag is explicitly passed
# ============================================================================

# Store original display environment before we clear it
_ORIGINAL_DISPLAY_ENV = {
    "DISPLAY": os.environ.get("DISPLAY", ""),
    "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
    "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", ""),
}

# Immediately clear display environment to prevent GUI connections
# This makes it IMPOSSIBLE for browsers to pop up accidentally
os.environ["DISPLAY"] = ""
os.environ["WAYLAND_DISPLAY"] = ""
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MOZ_HEADLESS"] = "1"
os.environ["CHROME_HEADLESS"] = "1"


def restore_display_environment():
    """Restore display environment for --visible mode (human debugging only)."""
    for key, value in _ORIGINAL_DISPLAY_ENV.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def pytest_configure(config):
    """Configure file-based database for browser tests.

    Critical fix: Browser tests with live_server need a file-based database
    instead of :memory: SQLite. This is because:
    1. live_server runs Django in a separate thread
    2. Each thread gets its own connection to the database
    3. :memory: SQLite creates a separate database per connection
    4. Result: fixtures in test thread are invisible to live_server thread

    Solution: Use a temporary file-based SQLite database that can be
    properly shared across threads.
    """
    from django.conf import settings  # noqa: PLC0415

    # Only apply to browser tests by checking if we're in the browser test directory
    # This is determined at configure time, before test collection
    test_paths = config.getoption("file_or_dir", default=None) or config.args
    is_browser_test_run = any("browser" in str(path) for path in test_paths)

    if not is_browser_test_run:
        return

    original_db_name = settings.DATABASES["default"]["NAME"]

    # Only override if we're using the in-memory database
    if original_db_name == ":memory:":
        # Create a temporary file-based database
        db_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
            delete=False, suffix=".sqlite3", prefix="test_browser_"
        )
        db_file.close()

        # Override database settings
        settings.DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": db_file.name,
                "ATOMIC_REQUESTS": False,
                "TEST": {
                    "NAME": db_file.name,
                },
            }
        }

    # Remove OIDC APPS to avoid conflicts with database SocialApp objects
    if hasattr(settings, "SOCIALACCOUNT_PROVIDERS"):
        if "openid_connect" in settings.SOCIALACCOUNT_PROVIDERS:
            settings.SOCIALACCOUNT_PROVIDERS["openid_connect"].pop("APPS", None)


def pytest_unconfigure(config):
    """Clean up any remaining temporary database files after tests complete."""
    # Cleanup any temp files that might have been left behind
    temp_dir = Path("/tmp")  # noqa: S108
    for temp_file in temp_dir.glob("test_browser_*.sqlite3"):
        with contextlib.suppress(OSError):
            temp_file.unlink()


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
        "--visible",
        action="store_true",
        default=False,
        help=(
            "Run browser tests with VISIBLE browser windows "
            "(for manual debugging only). "
            "By default, all browser tests run headless with display blocked. "
            "This flag is BLOCKED in CI and Claude Code environments."
        ),
    )
    parser.addoption(
        "--window-size",
        action="store",
        default="1920,1080",
        help="Browser window size (default: 1920,1080)",
    )


@pytest.fixture(scope="session")
def browser_config(request):
    """Get browser configuration from command-line options.

    By default, all browser tests run headless with display environment cleared.
    This prevents accidental GUI browser windows in automated testing.

    The --visible flag enables visible browser mode for manual debugging only.
    It is automatically blocked in CI and Claude Code environments.
    """
    visible_requested = request.config.getoption("--visible", default=False)

    # Check for automated environments
    is_ci = os.environ.get("CI", "false").lower() == "true"
    is_claudecode = os.environ.get("CLAUDECODE", "").lower() in ("1", "true")

    # BLOCK visible mode in automated environments with loud error
    if visible_requested and is_claudecode:
        error_msg = """
🚨🚨🚨 CRITICAL ERROR: --visible FLAG BLOCKED IN CLAUDE CODE 🚨🚨🚨

Claude Code environment detected! You attempted to use --visible flag.

❌ WHAT YOU DID WRONG:
You tried to run browser tests with visible browser windows.
This is PROHIBITED in Claude Code - it disturbs the user.

✅ WHAT YOU SHOULD DO INSTEAD:
Remove the --visible flag. Browser tests are headless by default.

Correct commands:
  make test                        # All tests, browser tests are headless
  make test-browser                # Browser tests only, headless
  uv run pytest tests/browser/     # Direct pytest, headless by default

🔧 THE --visible FLAG IS FOR:
- Manual debugging by HUMAN developers
- Visual inspection of animations/styling
- Local development ONLY (not automation)

Claude Code cannot use --visible. This is not negotiable.

DETECTED ENVIRONMENT:
  CLAUDECODE={claudecode}

PROHIBITED FLAG DETECTED:
  --visible

Please remove --visible and run tests in headless mode (the default).
"""
        pytest.exit(
            error_msg.format(claudecode=os.environ.get("CLAUDECODE")),
            returncode=1,
        )

    if visible_requested and is_ci:
        pytest.exit(
            "ERROR: --visible flag is blocked in CI environment. "
            "Browser tests must run headless in CI.",
            returncode=1,
        )

    # Restore display environment if visible mode requested (and allowed)
    if visible_requested:
        restore_display_environment()

    # headless = NOT visible (inverse relationship)
    headless = not visible_requested

    return {
        "browser": request.config.getoption("--browser"),
        "headless": headless,
        "visible": visible_requested,
        "window_size": request.config.getoption("--window-size"),
    }


@pytest.fixture
def chrome_options(browser_config):
    """Configure Chrome options.

    Headless mode is always enabled unless --visible flag is passed.
    Display environment is always cleared unless --visible flag is passed.
    """
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

    # CI/CD environment fixes
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=TranslateUI")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--remote-debugging-port=0")  # Use random port

    # Other useful options
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)  # noqa: FBT003

    # Suppress console logs
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    return options


@pytest.fixture
def firefox_options(browser_config):
    """Configure Firefox options.

    Headless mode is always enabled unless --visible flag is passed.
    Display environment is always cleared unless --visible flag is passed.
    """
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
        msg = f"Unsupported browser: {browser}"
        raise ValueError(msg)

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
    django_user_model.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",  # noqa: S106
    )

    # Navigate to login page
    driver.get(f"{live_server_url}/accounts/login/")

    # Find and fill login form
    # Wait for login form to be present
    wait = WebDriverWait(driver, 10)

    # Fill in credentials
    username_field = wait.until(
        expected_conditions.presence_of_element_located((By.NAME, "login")),
    )
    username_field.send_keys("testuser")

    password_field = driver.find_element(By.NAME, "password")
    password_field.send_keys("testpass123")

    # Submit form
    submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
    submit_button.click()

    # Wait for redirect after successful login
    wait.until(
        expected_conditions.url_changes(f"{live_server_url}/accounts/login/"),
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
        screenshots_path = Path(screenshots_dir)
        screenshots_path.mkdir(parents=True, exist_ok=True)

        # Generate screenshot filename
        test_name = request.node.name.replace("[", "_").replace("]", "_")
        screenshot_path = screenshots_path / f"failure_{test_name}.png"

        # Take screenshot
        driver.save_screenshot(screenshot_path)
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
        screenshots_path = Path("tests/browser/screenshots")
        screenshots_path.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshots_path / f"{name}.png"
        driver.save_screenshot(str(screenshot_path))
        return str(screenshot_path)

    return _take_screenshot


@pytest.fixture(scope="session")
def social_apps(django_db_setup, django_db_blocker):
    """Create SocialApp objects for all OAuth providers so buttons appear in UI.

    This fixture creates Social App objects that are visible to both the test
    and the live_server thread. With the file-based database configured in
    pytest_configure, the data is properly shared across threads.

    Browser tests that need OAuth buttons should use this fixture.

    Session-scoped to prevent duplicate SocialApp creation in parallel tests.
    Must aggressively clean up SocialApps created by unit tests that run first.
    """
    with django_db_blocker.unblock():
        # CRITICAL: Aggressively delete ALL existing SocialApps
        # Unit tests create SocialApps before browser tests run, and they persist
        # in the file-based database even after transaction rollback

        # Use raw SQL to bypass Django's transaction management
        with connection.cursor() as cursor:
            # Delete many-to-many relationships first
            cursor.execute(
                "DELETE FROM socialaccount_socialapp_sites "
                "WHERE socialapp_id IN "
                "(SELECT id FROM socialaccount_socialapp)"
            )
            # Then delete SocialApp objects
            cursor.execute("DELETE FROM socialaccount_socialapp")

        # Commit deletion and force database sync
        transaction.commit()

        # Force SQLite to checkpoint and sync (for file-based database)
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA wal_checkpoint(RESTART)")
            cursor.execute("PRAGMA synchronous=FULL")

        # Close all connections to force reconnect
        for conn in connections.all():
            conn.close()

        # Get the current site
        site = Site.objects.get_current()

        # Create test SocialApp objects
        github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Browser Test App",
            client_id="browser_test_github_client_id",
            secret="browser_test_github_secret",  # noqa: S106
        )
        github_app.sites.add(site)

        google_app = SocialApp.objects.create(
            provider="google",
            name="Google Browser Test App",
            client_id="browser_test_google_client_id.apps.googleusercontent.com",
            secret="browser_test_google_secret",  # noqa: S106
        )
        google_app.sites.add(site)

        gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Browser Test App",
            client_id="browser_test_gitlab_application_id",
            secret="browser_test_gitlab_secret",  # noqa: S106
        )
        gitlab_app.sites.add(site)

        linkedin_app = SocialApp.objects.create(
            provider="openid_connect",
            provider_id="linkedin",  # CRITICAL: Must set provider_id field for OIDC
            name="LinkedIn",
            client_id="browser_test_linkedin_client_id",
            secret="browser_test_linkedin_secret",  # noqa: S106
            settings={
                "server_url": "https://www.linkedin.com/oauth",
            },
        )
        linkedin_app.sites.add(site)

        discord_app = SocialApp.objects.create(
            provider="discord",
            name="Discord Browser Test App",
            client_id="browser_test_discord_client_id",
            secret="browser_test_discord_secret",  # noqa: S106
        )
        discord_app.sites.add(site)

        # Commit creation and force database sync
        transaction.commit()

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA wal_checkpoint(RESTART)")
            cursor.execute("PRAGMA synchronous=FULL")

        for conn in connections.all():
            conn.close()

    yield

    # Cleanup after all tests complete
    with django_db_blocker.unblock():
        SocialApp.objects.all().delete()
        transaction.commit()
