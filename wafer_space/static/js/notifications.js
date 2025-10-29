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
