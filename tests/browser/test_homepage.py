"""
Browser tests for the homepage.
"""
import pytest
from selenium.webdriver.common.by import By

from tests.browser.base import BaseBrowserTest
from tests.browser.pages.home_page import HomePage


@pytest.mark.django_db
class TestHomePage(BaseBrowserTest):
    """Test the homepage functionality."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def test_homepage_loads(self, driver):
        """Test that the homepage loads correctly."""
        # Create page object
        home_page = HomePage(driver, self.live_server_url)

        # Navigate to homepage
        home_page.go_to_home_page()

        # Verify page loaded
        assert home_page.verify_page_loaded()

        # Check page title
        title = home_page.get_title()
        assert "wafer" in title.lower() or "home" in title.lower()

        # Check navbar is visible
        assert home_page.is_navbar_visible()

    def test_navigation_links_visible(self, driver):
        """Test that navigation links are visible on homepage."""
        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Check for Sign In link (when not authenticated)
        sign_in_link = driver.find_elements(By.LINK_TEXT, "Sign In")
        sign_up_link = driver.find_elements(By.LINK_TEXT, "Sign Up")

        # At least one authentication link should be visible
        assert sign_in_link or sign_up_link, "No authentication links found"

    def test_about_page_navigation(self, driver):
        """Test navigation to about page."""
        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Navigate to about page
        about_link = driver.find_elements(By.LINK_TEXT, "About")
        if about_link:
            about_link[0].click()
            self.wait_for_url_contains(driver, "/about/")
            assert "/about/" in driver.current_url

    def test_homepage_responsive_mobile(self, driver):
        """Test homepage responsiveness on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone 6/7/8 size

        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Check if navbar toggler is visible (indicates mobile view)
        navbar_toggler = driver.find_elements(By.CLASS_NAME, "navbar-toggler")
        if navbar_toggler:
            msg = "Navbar toggler not visible in mobile view"
            assert navbar_toggler[0].is_displayed(), msg

    def test_homepage_responsive_tablet(self, driver):
        """Test homepage responsiveness on tablet viewport."""
        # Set tablet viewport
        driver.set_window_size(768, 1024)  # iPad size

        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Verify page loads correctly
        assert home_page.verify_page_loaded()

    def test_homepage_responsive_desktop(self, driver):
        """Test homepage responsiveness on desktop viewport."""
        # Set desktop viewport
        driver.set_window_size(1920, 1080)

        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Verify page loads correctly
        assert home_page.verify_page_loaded()

        # Check that navbar is in desktop mode (no toggler visible)
        navbar_toggler = driver.find_elements(By.CLASS_NAME, "navbar-toggler")
        if navbar_toggler:
            msg = "Navbar toggler should not be visible in desktop view"
            assert not navbar_toggler[0].is_displayed(), msg

    def test_no_javascript_errors(self, driver):
        """Test that homepage loads without JavaScript errors."""
        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Check for JavaScript errors
        self.check_for_javascript_errors(driver)

    def test_page_performance(self, driver):
        """Test basic page performance metrics."""
        home_page = HomePage(driver, self.live_server_url)
        home_page.go_to_home_page()

        # Wait for page to fully load
        self.wait_for_page_load(driver)

        # Get performance timing
        performance = driver.execute_script(
            "return window.performance.timing",
        )

        # Calculate page load time
        load_time = performance["loadEventEnd"] - performance["navigationStart"]

        # Assert reasonable load time (adjust threshold as needed)
        PAGE_LOAD_THRESHOLD = 5000
        assert load_time < PAGE_LOAD_THRESHOLD, f"Page load time too slow: {load_time}ms"

        # Log performance metrics for debugging
        dom_ready = (
            performance["domContentLoadedEventEnd"] - performance["navigationStart"]
        )
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Performance Metrics:")
        logger.info("  Total Load Time: %dms", load_time)
        logger.info("  DOM Ready: %dms", dom_ready)
