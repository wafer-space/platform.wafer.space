/*
 * Shuttle deadlines (#349): show each deadline in the reader's time zone
 * and count down to it, as wafer.space does.
 *
 * Both read only the server's UTC instant (the <time datetime> and
 * data-countdown attributes), never a formatted display string, so a wrong
 * browser clock can only show a wrong countdown, never a wrong deadline.
 * Dates are written day first ("17 December 2026, 22:29 ACDT").
 */
(function () {
  'use strict';

  const PASSED_TEXT = 'Deadline passed';

  function zoneName(date) {
    // The reader's own locale names the zone best (ACDT, CET, ...); fall
    // back to the numeric offset it gives otherwise.
    const part = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
      .formatToParts(date)
      .find((p) => p.type === 'timeZoneName');
    return part ? part.value : '';
  }

  function localText(date) {
    const dayFirst = new Intl.DateTimeFormat('en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      hourCycle: 'h23',  // never "24:00" for midnight
    }).formatToParts(date);
    const get = (type) => dayFirst.find((p) => p.type === type).value;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return `${get('day')} ${get('month')} ${get('year')}, ${get('hour')}:${get('minute')} ${zoneName(date)} (${tz})`;
  }

  function compactText(msLeft) {
    const totalHours = Math.floor(msLeft / 3600000);
    const days = Math.floor(totalHours / 24);
    return days > 0 ? `${days} d ${totalHours % 24} h left` : `${totalHours} h ${Math.floor((msLeft % 3600000) / 60000)} m left`;
  }

  function countdownText(msLeft) {
    const totalSeconds = Math.floor(msLeft / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return `${days} day${days === 1 ? '' : 's'} ${hours} h ${minutes} m ${seconds} s left`;
  }

  function showLocalTimes() {
    document.querySelectorAll('time[data-local-time]').forEach((el) => {
      const instant = new Date(el.getAttribute('datetime'));
      if (!Number.isNaN(instant.getTime())) {
        el.textContent = localText(instant);
      }
    });
  }

  function tick() {
    const now = Date.now();
    document.querySelectorAll('[data-countdown]').forEach((el) => {
      const deadline = new Date(el.getAttribute('data-countdown')).getTime();
      if (Number.isNaN(deadline)) {
        return;
      }
      const left = deadline - now;
      if (left <= 0) {
        el.textContent = PASSED_TEXT;
        el.removeAttribute('data-countdown');
        el.setAttribute('data-deadline-passed', '');
        el.classList.remove('bg-warning', 'text-dark');
        el.classList.add('bg-secondary');
      } else if (el.hasAttribute('data-countdown-compact')) {
        el.textContent = compactText(left);
      } else {
        el.textContent = countdownText(left);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    showLocalTimes();
    if (document.querySelector('[data-countdown]')) {
      tick();
      window.setInterval(tick, 1000);
    }
  });
})();
