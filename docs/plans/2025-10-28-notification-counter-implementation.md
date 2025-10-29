# Notification Counter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add visual notification counter badge to navigation bar that updates automatically via JavaScript polling

**Architecture:** Server-side context processor injects initial count, JavaScript polls REST API endpoint every 45 seconds (only when tab visible), Bootstrap badge overlay on bell icon

**Tech Stack:** Django context processors, Django REST views, vanilla JavaScript (Page Visibility API), Bootstrap 5, CSS positioning

---

## Task 1: Context Processor for Unread Count

**Files:**
- Create: `wafer_space/notifications/context_processors.py`
- Modify: `config/settings/base.py:80-95` (TEMPLATES.OPTIONS.context_processors)

**Step 1: Write the failing test**

Create: `wafer_space/notifications/tests/test_context_processors.py`

```python
"""Tests for notification context processors."""

from django.test import RequestFactory, TestCase

from wafer_space.notifications.context_processors import unread_notifications_count
from wafer_space.notifications.models import Notification
from wafer_space.users.models import User


class TestUnreadNotificationsCount(TestCase):
    """Test the unread_notifications_count context processor."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_returns_zero_for_unauthenticated_user(self):
        """Test that unauthenticated users get zero count."""
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/")
        request.user = AnonymousUser()

        context = unread_notifications_count(request)

        assert context["unread_count"] == 0

    def test_returns_zero_when_no_notifications(self):
        """Test that users with no notifications get zero count."""
        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == 0

    def test_returns_correct_count_with_unread_notifications(self):
        """Test that unread notification count is correct."""
        # Create 3 unread notifications
        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == 3

    def test_excludes_read_notifications(self):
        """Test that read notifications are not counted."""
        # Create 2 unread and 3 read notifications
        for i in range(2):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Unread {i}",
                message="Test message",
                is_read=False,
            )

        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_FAILED,
                title=f"Read {i}",
                message="Test message",
                is_read=True,
            )

        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == 2
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/notifications/tests/test_context_processors.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'wafer_space.notifications.context_processors'"

**Step 3: Write minimal implementation**

Create: `wafer_space/notifications/context_processors.py`

```python
"""Context processors for notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest


def unread_notifications_count(request: HttpRequest) -> dict[str, int]:
    """Add unread notification count to template context.

    Args:
        request: The HTTP request object

    Returns:
        Dictionary with unread_count key
    """
    if not request.user.is_authenticated:
        return {"unread_count": 0}

    from .models import Notification

    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return {"unread_count": count}
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest wafer_space/notifications/tests/test_context_processors.py -v
```

Expected: PASS (4 tests)

**Step 5: Register context processor in settings**

Modify: `config/settings/base.py`

Find the TEMPLATES section (around line 80-95) and add the context processor:

```python
TEMPLATES = [
    {
        # ... existing config
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "wafer_space.users.context_processors.allauth_settings",
                "wafer_space.notifications.context_processors.unread_notifications_count",  # ← ADD THIS LINE
            ],
        },
    },
]
```

**Step 6: Run linting and type checking**

```bash
make lint-fix && make lint && make type-check
```

Expected: All checks pass

**Step 7: Commit**

```bash
git add wafer_space/notifications/context_processors.py
git add wafer_space/notifications/tests/test_context_processors.py
git add config/settings/base.py
git commit -m "Add context processor for unread notification count

Implements server-side injection of unread notification count into all
template contexts. Returns 0 for unauthenticated users, actual count for
authenticated users. Excludes read notifications from count.

Registered in settings.py context_processors list.

wafer_space/notifications/context_processors.py:19-30
config/settings/base.py:~88

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: API Endpoint URL Registration

**Files:**
- Modify: `wafer_space/notifications/urls.py:~10-15`

**Step 1: Write the failing test**

Add to: `wafer_space/notifications/tests/test_views.py` (end of file)

```python
def test_get_unread_count_api_authenticated(self):
    """Test that API returns correct unread count for authenticated users."""
    # Create 5 unread notifications
    for i in range(5):
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title=f"Notification {i}",
            message="Test message",
            is_read=False,
        )

    self.client.login(username="testuser", password="testpass123")
    response = self.client.get(reverse("notifications:unread_count"))

    assert response.status_code == 200
    assert response.json() == {"unread_count": 5}


def test_get_unread_count_api_unauthenticated(self):
    """Test that API requires authentication."""
    response = self.client.get(reverse("notifications:unread_count"))

    # Should redirect to login
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/notifications/tests/test_views.py::test_get_unread_count_api_authenticated -v
uv run pytest wafer_space/notifications/tests/test_views.py::test_get_unread_count_api_unauthenticated -v
```

Expected: FAIL with "NoReverseMatch: Reverse for 'unread_count' not found"

**Step 3: Add URL pattern**

Modify: `wafer_space/notifications/urls.py`

The view `get_unread_count` already exists in views.py, and main already
registers the URL pattern (no change needed):

```python
urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("<uuid:notification_id>/read/", views.mark_notification_read, name="read"),
    path("mark-all-read/", views.mark_all_notifications_read, name="mark_all_read"),
    path("unread-count/", views.get_unread_count, name="unread_count"),
]
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/notifications/tests/test_views.py::test_get_unread_count_api_authenticated -v
uv run pytest wafer_space/notifications/tests/test_views.py::test_get_unread_count_api_unauthenticated -v
```

Expected: PASS (2 tests)

**Step 5: Run full notification tests**

```bash
uv run pytest wafer_space/notifications/tests/ -v
```

Expected: All tests pass

**Step 6: Run linting**

```bash
make lint-fix && make lint
```

Expected: All checks pass

**Step 7: Commit**

```bash
git add wafer_space/notifications/urls.py
git add wafer_space/notifications/tests/test_views.py
git commit -m "Add URL route for unread count API endpoint

Maps /notifications/unread-count/ to get_unread_count view.
Includes tests for authenticated and unauthenticated access.

wafer_space/notifications/urls.py:14

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Badge HTML and CSS

**Files:**
- Modify: `wafer_space/templates/base.html:~50-60` (notification bell section)
- Modify: `wafer_space/static/css/project.css:~end`

**Step 1: Update base template with badge HTML**

Modify: `wafer_space/templates/base.html`

Find the notification bell link (search for `bi-bell`) and replace with:

```html
<a href="{% url 'notifications:list' %}"
   class="nav-link position-relative{% if unread_count > 0 %} has-unread{% endif %}"
   id="notification-bell">
  <svg class="bi bi-bell" width="1em" height="1em">
    <use xlink:href="#bi-bell"></use>
  </svg>
  {% if unread_count > 0 %}
  <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger"
        id="notification-badge">
    {% if unread_count > 99 %}99+{% else %}{{ unread_count }}{% endif %}
    <span class="visually-hidden">unread notifications</span>
  </span>
  {% endif %}
</a>
```

**Step 2: Add CSS styling**

Modify: `wafer_space/static/css/project.css` (add to end of file)

```css
/* Notification badge positioning and styling */
#notification-badge {
  font-size: 0.65rem;      /* Small, compact text */
  min-width: 1.25em;       /* Minimum width for circular shape */
  height: 1.25em;          /* Fixed height */
  line-height: 1.25em;     /* Center text vertically */
  padding: 0 0.4em;        /* Horizontal padding for wider numbers */
  z-index: 10;             /* Above other elements */
}

/* Bell icon color change when unread notifications exist */
#notification-bell.has-unread .bi-bell {
  fill: #dc3545;           /* Bootstrap danger red */
}
```

**Step 3: Run linting**

```bash
make lint-fix && make lint
```

Expected: All checks pass

**Step 4: Manual visual verification**

```bash
make runserver
```

1. Open http://localhost:8081
2. Log in
3. Navigate to notifications page
4. Check bell icon in navbar:
   - Badge should be hidden if 0 unread
   - Badge should show count if >0 unread
   - Bell should be red if unread notifications exist

**Step 5: Commit**

```bash
git add wafer_space/templates/base.html
git add wafer_space/static/css/project.css
git commit -m "Add notification badge to navigation bar

Adds Bootstrap badge overlay on notification bell icon:
- Displays count for 1-99 unread notifications
- Shows '99+' for 100+ unread
- Hidden when count is zero
- Bell icon turns red when unread notifications exist

Uses context processor to inject initial count on page load.

wafer_space/templates/base.html:~50-60
wafer_space/static/css/project.css:~end

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: JavaScript Auto-Update Implementation

**Files:**
- Create: `wafer_space/static/js/notifications.js`
- Modify: `wafer_space/templates/base.html:~end` (before `</body>`)

**Step 1: Create JavaScript file**

Create: `wafer_space/static/js/notifications.js`

```javascript
/**
 * Notification Badge Auto-Update
 *
 * Polls the server every 45 seconds for unread notification count.
 * Only polls when the browser tab is visible (active).
 */

(function() {
  'use strict';

  const POLL_INTERVAL = 45000; // 45 seconds
  const BADGE_ENDPOINT = '/notifications/unread-count/';

  let pollTimer = null;
  let isTabVisible = !document.hidden;

  /**
   * Update the notification badge with new count.
   */
  function updateBadge(count) {
    const bell = document.getElementById('notification-bell');
    const badge = document.getElementById('notification-badge');

    if (!bell) return;

    if (count > 0) {
      // Update or create badge
      const displayCount = count > 99 ? '99+' : count.toString();

      if (badge) {
        // Update existing badge text (only the text node, not the screen reader span)
        const textNode = badge.firstChild;
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
          textNode.textContent = displayCount;
        }
      } else {
        // Create badge if it doesn't exist
        const newBadge = document.createElement('span');
        newBadge.id = 'notification-badge';
        newBadge.className = 'position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger';
        newBadge.textContent = displayCount;

        const srText = document.createElement('span');
        srText.className = 'visually-hidden';
        srText.textContent = 'unread notifications';
        newBadge.appendChild(srText);

        bell.appendChild(newBadge);
      }

      // Add color change class
      bell.classList.add('has-unread');
    } else {
      // Remove badge if count is zero
      if (badge) {
        badge.remove();
      }
      bell.classList.remove('has-unread');
    }
  }

  /**
   * Fetch unread count from server.
   */
  function fetchUnreadCount() {
    fetch(BADGE_ENDPOINT)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        updateBadge(data.unread_count);
      })
      .catch(error => {
        console.error('Failed to fetch unread count:', error);
      });
  }

  /**
   * Start polling for updates.
   */
  function startPolling() {
    if (pollTimer) return; // Already polling

    pollTimer = setInterval(() => {
      if (isTabVisible) {
        fetchUnreadCount();
      }
    }, POLL_INTERVAL);
  }

  /**
   * Stop polling for updates.
   */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  /**
   * Handle visibility changes (tab switching).
   */
  function handleVisibilityChange() {
    isTabVisible = !document.hidden;

    if (isTabVisible) {
      // Tab became visible - fetch immediately and resume polling
      fetchUnreadCount();
      startPolling();
    } else {
      // Tab became hidden - stop polling to save resources
      stopPolling();
    }
  }

  // Initialize on page load
  document.addEventListener('DOMContentLoaded', function() {
    // Only enable auto-update if user is authenticated
    const bell = document.getElementById('notification-bell');
    if (!bell) return; // No bell = not logged in

    // Set up visibility change listener
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Start polling if tab is visible
    if (isTabVisible) {
      startPolling();
    }
  });

  // Cleanup on page unload
  window.addEventListener('beforeunload', function() {
    stopPolling();
  });
})();
```

**Step 2: Include JavaScript in base template**

Modify: `wafer_space/templates/base.html` (before `</body>` tag, around line 150-160)

Add:

```html
{% if user.is_authenticated %}
  <script src="{% static 'js/notifications.js' %}"></script>
{% endif %}
```

**Step 3: Run linting**

```bash
make lint-fix && make lint
```

Expected: All checks pass

**Step 4: Manual testing - JavaScript polling**

```bash
make runserver
```

1. Open http://localhost:8081 and log in
2. Open browser DevTools → Network tab
3. Filter by "unread-count"
4. Wait 45 seconds → Verify API call appears
5. Switch to different tab → Wait 45 seconds → No API calls
6. Switch back → Immediate API call + resume polling

**Step 5: Manual testing - Badge updates**

In a separate terminal/browser:

```bash
# Create notification via Django shell
uv run python manage.py shell

from wafer_space.users.models import User
from wafer_space.notifications.models import Notification
user = User.objects.get(username='<your-username>')
Notification.objects.create(
    user=user,
    notification_type=Notification.Type.DOWNLOAD_COMPLETE,
    title='Test',
    message='Test',
    is_read=False
)
```

Wait up to 45 seconds → Badge should appear with count

**Step 6: Commit**

```bash
git add wafer_space/static/js/notifications.js
git add wafer_space/templates/base.html
git commit -m "Add JavaScript auto-update for notification badge

Polls /notifications/unread-count/ every 45 seconds:
- Only polls when browser tab is active (Page Visibility API)
- Updates badge count dynamically (creates/removes badge as needed)
- Immediate fetch when tab becomes visible
- Handles network errors gracefully

Loaded only for authenticated users.

wafer_space/static/js/notifications.js
wafer_space/templates/base.html:~155

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Browser Tests for Badge Display

**Files:**
- Create: `tests/browser/test_notifications/test_notification_badge.py`

**Step 1: Write browser tests**

Create: `tests/browser/test_notifications/test_notification_badge.py`

```python
"""Browser tests for notification badge functionality."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService, TermsOfServiceAcceptance
from wafer_space.notifications.models import Notification
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"


@pytest.mark.browser
class TestNotificationBadge(BaseBrowserTest):
    """Test notification badge display and behavior."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up test with authenticated user."""
        self.driver = driver
        self.live_server_url = live_server.url

        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_USER_AUTH,
        )

        # Verify email
        EmailAddress.objects.create(
            user=self.user,
            email="test@example.com",
            verified=True,
            primary=True,
        )

        # Accept TOS
        tos = TermsOfService.get_active()
        if tos:
            TermsOfServiceAcceptance.objects.create(
                user=self.user,
                tos_version=tos,
                ip_address="127.0.0.1",
            )

    def login(self):
        """Log in as test user."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")

        username_input.send_keys("testuser")
        password_input.send_keys(TEST_USER_AUTH)

        current_url = self.driver.current_url
        submit_button = self.driver.find_element(
            By.CSS_SELECTOR,
            'button[type="submit"]',
        )
        submit_button.click()

        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.url_changes(current_url))

    def test_badge_not_displayed_when_zero_unread(self):
        """Test that badge is hidden when there are no unread notifications."""
        self.login()
        self.navigate_to(self.driver, "/")

        # Check that bell exists but badge does not
        bell = self.wait_for_element(self.driver, (By.ID, "notification-bell"))
        assert bell is not None

        # Badge should not exist
        badges = self.driver.find_elements(By.ID, "notification-badge")
        assert len(badges) == 0

    def test_badge_displays_with_unread_count(self):
        """Test that badge displays with correct count."""
        # Create 3 unread notifications
        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check badge exists and shows correct count
        badge = self.wait_for_element(self.driver, (By.ID, "notification-badge"))
        assert "3" in badge.text

    def test_badge_displays_99_plus_for_large_counts(self):
        """Test that badge shows '99+' for counts over 99."""
        # Create 105 unread notifications
        for i in range(105):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check badge shows 99+
        badge = self.wait_for_element(self.driver, (By.ID, "notification-badge"))
        assert "99+" in badge.text

    def test_bell_icon_color_changes_with_unread(self):
        """Test that bell icon changes color when there are unread notifications."""
        # Create 1 unread notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check bell has 'has-unread' class
        bell = self.wait_for_element(self.driver, (By.ID, "notification-bell"))
        assert "has-unread" in bell.get_attribute("class")
```

**Step 2: Run tests to verify they pass**

```bash
uv run pytest tests/browser/test_notifications/test_notification_badge.py -v
```

Expected: PASS (4 tests) - may take 1-2 minutes due to browser startup

**Step 3: Run linting**

```bash
make lint-fix && make lint
```

Expected: All checks pass

**Step 4: Commit**

```bash
git add tests/browser/test_notifications/test_notification_badge.py
git commit -m "Add browser tests for notification badge

Tests badge display, count accuracy, 99+ display, and bell color change.
All tests use headless browser mode.

tests/browser/test_notifications/test_notification_badge.py

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Final Verification and Documentation

**Files:**
- Modify: `docs/plans/2025-10-28-notification-counter-design.md:~end`

**Step 1: Run full test suite**

```bash
make test
```

Expected: All tests pass (498+ tests including new ones)

**Step 2: Run all linting and type checking**

```bash
make lint-fix && make lint && make type-check
```

Expected: All checks pass

**Step 3: Run browser tests specifically**

```bash
make test-browser-headless
```

Expected: All browser tests pass

**Step 4: Update design document with implementation notes**

Modify: `docs/plans/2025-10-28-notification-counter-design.md`

Add to end of file:

```markdown
## Implementation Notes

**Implemented**: 2025-10-28

**Commits**:
- Context processor and tests
- API endpoint URL registration
- Badge HTML and CSS
- JavaScript auto-update
- Browser tests

**Testing**:
- Unit tests: 6 new tests (context processor + API endpoint)
- Browser tests: 4 new tests (badge display + behavior)
- All 498+ tests passing

**Manual Testing Completed**:
- Badge displays correctly with various counts (0, 1, 3, 99+)
- Bell icon color changes with unread notifications
- JavaScript polling works (verified in Network tab)
- Tab visibility detection works (polling stops when hidden)
- Badge updates dynamically after 45 seconds

**Known Issues**: None

**Browser Compatibility**: Tested in Chrome headless (CI), works in all modern browsers
```

**Step 5: Commit documentation update**

```bash
git add docs/plans/2025-10-28-notification-counter-design.md
git commit -m "Add implementation notes to design document

Documents successful implementation with commit summary, test results,
and manual testing verification.

docs/plans/2025-10-28-notification-counter-design.md:~end

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Step 6: Final verification in worktree**

```bash
# Verify clean git status
git status

# Verify all commits present
git log --oneline -6

# Verify on feature branch
git branch --show-current
```

Expected:
- Clean working directory
- 6 commits on feature/notification-counter branch
- Ready for merge

---

## Completion

**Total Tasks**: 6
**Total Steps**: ~35
**Estimated Time**: 45-60 minutes
**Files Modified**: 8
**Files Created**: 4
**Tests Added**: 10

**Ready for**:
- Code review
- Merge to main
- Deployment

**Related Skills**:
- @superpowers:verification-before-completion - Use before claiming complete
- @superpowers:finishing-a-development-branch - Use to complete worktree workflow

---

## Implementation Notes

**Implemented**: 2025-10-29

**Commits** (rebased onto main 2026-06-11, so SHAs have changed):
- Context processor and tests
- Tests for existing unread count API endpoint
- Badge HTML and CSS
- JavaScript auto-update
- Browser tests

**Rebase Notes (2026-06-11)**:
- main already provides `/notifications/unread-count/` via
  `get_unread_count`, so no URL route was added; the planned
  `api/` prefix rename was dropped to keep main's URL structure.

**Testing**:
- Unit tests: 6 new tests (4 context processor + 2 API endpoint)
- Browser tests: 4 new tests (badge display + behavior)
- All tests passing: 504 passed, 1 skipped

**Features Implemented**:
- Badge displays unread notification count on bell icon
- Badge shows "99+" for counts >= 100
- Badge hidden when count is zero
- Bell icon turns red when unread notifications exist
- JavaScript polls every 45 seconds for count updates
- Polling stops when browser tab is hidden (Page Visibility API)
- Progressive enhancement - works without JavaScript

**Code Quality**:
- All linting checks pass (ruff)
- All type checks pass (mypy)
- No code suppressions added
- 139 files verified clean

**Browser Compatibility**: Tested in headless Chrome/Firefox, compatible with all modern browsers

**Known Issues**: None

**Manual Testing Required**:
- Verify badge updates after 45 seconds with new notifications
- Verify polling stops when tab hidden (check Network tab)
- Verify badge disappears when all notifications marked as read
- Verify icon color change with unread notifications
