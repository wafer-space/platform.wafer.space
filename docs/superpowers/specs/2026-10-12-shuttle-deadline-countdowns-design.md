# Shuttle deadline dates and countdowns — Design

**Date:** 2026-10-12
**Branch:** `issue/349-deadline-countdowns`
**Issue:** #349 (Tim, 11 Oct 2026: "make sure the platform website clearly
shows the deadline dates and count downs in a similar manner to the
website. Show both in AoE and the user's timezone.")
**Builds on:** #351 (`shuttle_dates` filters: `aoe_deadline`,
`milestone_date`), #365 (`shuttles/_shuttle_state.html`, the shuttle state
include used on the project page, the project form and the shuttle pages).
**Status:** Draft for the coordinator's review.

## What the website does

`wafer-space.github.io` (`_data/runs.yml`, `_includes/components/countdown.html`)
shows each deadline with:

- the display date with the zone named and linked: "16 December 2026 @
  11:59 PM AoE" (AoE linked to Wikipedia's "Anywhere on Earth");
- a "see in your timezone" link to timeanddate.com
  (`fixedtime.html?iso=20261216T2359&p1=3399`);
- a live countdown of days, hours, minutes and seconds (`data-date` holds the
  UTC instant), replaced by an expired message ("Submissions closed") when it
  reaches zero.

Milestones (production start, delivery) are shown as plain dates, with no
time, zone or countdown.

## Design

### 1. One include for a deadline: `shuttles/_deadline.html`

It takes a `deadline` (an aware datetime) and an optional `label`, and
renders:

- the AoE text from the existing `aoe_deadline` filter, with "AoE" linked
  as on the website;
- **the user's timezone**: a `<time datetime="<ISO UTC>" data-local-time>`
  element whose text the script fills from the browser
  (`Intl.DateTimeFormat` with `timeZoneName: "short"`), for example
  "17 December 2026, 10:29 pm ACDT". Without JavaScript it falls back to the
  website's "see in your timezone" timeanddate link, which the new filter
  `timeanddate_url` builds the same way the website does;
- **a countdown**: `<span data-countdown="<ISO UTC>">` showing, for example,
  "65 days 22 h 14 m 3 s left", updated every second. At zero it is replaced
  by "Deadline passed". When the page loads after the deadline, the server
  renders "Deadline passed" directly, so a stale page never counts below
  zero.

### 2. One small script: `static/js/shuttle_deadlines.js`

It is loaded once with `defer` from `base.html` and finds every
`[data-local-time]` and `[data-countdown]`. A standalone file, not inline:
the project form's inline script shares one `DOMContentLoaded` scope (a
`SyntaxError` there kills all form JS), so it stays out of that scope. One
`setInterval` per page updates every countdown. It does nothing when no such
element exists.

### 3. Where it appears

| Place | Today | After |
| --- | --- | --- |
| `_shuttle_state.html` (project page, project form, shuttle list, shuttle detail header, assignment page) | "GDS due 16 December 2026 @ 11:59 PM AoE" | the include, labelled "GDS submission deadline": AoE text, the user's local time, countdown |
| Shuttle detail, "Submission Deadline" row | AoE text | the include |
| Shuttle list card | AoE text | the include |
| Projects list (`/projects/`) | no shuttle dates | **out of scope here.** Open PR #321 (lane B) adds the shuttle column; a compact countdown there follows after #321 merges, as a small follow-up |
| Milestones (production start, estimated or actual completion) | `milestone_date` | unchanged: date-only values stored as midnight UTC, like the website's plain dates. No countdown and no local time, since a date has no time to convert |

The purchase (campaign) deadline is not a platform field. It lives on the
website and CrowdSupply, so it is out of scope. The run-page link that
`_shuttle_state.html` already shows covers it.

### 4. Closed shuttles

`_shuttle_state.html` shows "Closed" and no deadline when
`shuttle.is_closed` (#320/#350). That stays: a closed shuttle has no live
deadline, so no countdown is shown.

## Error handling

- A missing deadline: the include is guarded with `{% if %}` at every call
  site, as the existing filters require (they raise on `None`).
- Naive datetimes: the existing `_require_aware` raises; the new filters
  reuse it.
- A browser without `Intl`: the AoE text and the timeanddate link remain and
  the local-time element keeps its fallback text.

## Testing

- Filters: `timeanddate_url` for the G803 deadline gives
  `…fixedtime.html?iso=20261216T2359&p1=3399`; `iso_utc` gives
  `2026-12-17T11:59:59Z`; both raise on `None` and on naive datetimes.
- Include: renders the AoE text, the `<time datetime>` and
  `data-countdown` attributes with the UTC instant, the fallback link; a past
  deadline renders "Deadline passed" and no `data-countdown`.
- Pages: the project page, the shuttle detail and the shuttle list contain the
  include's markers for an open shuttle with a deadline; a closed shuttle
  shows none.
- Browser test (headless, with the browser time zone set to
  Australia/Adelaide through the Chrome DevTools protocol, and a deadline
  computed relative to now):
  - the local time shows the converted time and "ACDT";
  - the countdown shows the expected day count and changes within two
    seconds;
  - a deadline a few seconds ahead switches to "Deadline passed";
  - no JS errors.

## Out of scope

- The projects list countdown (after #321).
- Owner warnings close to the deadline: that is #347, next.
- Email: #249, parked.
