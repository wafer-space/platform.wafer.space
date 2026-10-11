# Warn owners near the GDS submission deadline — Design

**Date:** 2026-10-12
**Branch:** `issue/347-deadline-warning`
**Issue:** #347 ("Nothing on the platform warns a project owner that the GDS
submission deadline of their project's shuttle is close.")
**Decisions:** Tim, dates-01 (11 Oct): log a bug about warning when close to
the deadline. Tim, issues-05 (11 Oct): no email sending for now; improving the
notifications system is a big task to be designed separately. So the warning
is **on-site only**, shown in the pages themselves, and leaves the
notifications system alone.
**Builds on:** #349 (`shuttle_deadline` tag: AoE date, local time,
countdown), #320/#350 (`Shuttle.is_closed`).
**Status:** Draft for the coordinator's review.

## Who is warned, and when

A project needs the warning when all of these hold:

- it is on a shuttle that is open (`not shuttle.is_closed`) and has a
  `submission_deadline`;
- the deadline is in the future and **within 14 days**;
- it has **no file submitted for manufacturing** (`submitted_file is None`);
- it is not archived (#307).

There are two levels:
- **warning** (yellow) up to 14 days before;
- **urgent** (red) within the last 3 days.

Both thresholds are module constants in one place, so they can be retuned.
Default: 14 days and 3 days (open question 1).

The rule is one model method, `Project.deadline_warning() -> str | None`. It
returns `"warning"`, `"urgent"` or `None`, so every page asks the same
question.

## Where it is shown

1. **Project page** (`project_detail.html`): a banner above the page header,
   to the owner and to staff:
   - "The GDS submission deadline for G803 is close: {% shuttle_deadline %}.
     This project has no file submitted for manufacturing yet."
   - A second line names the next step, matching the page's own state: no
     file yet ("Submit a file URL"), a file still being checked ("Wait for
     the manufacturability check to finish, then submit"), or a passing file
     ("Submit for Manufacturing").
2. **Projects list** (`/projects/`): one alert at the top, for the signed-in
   user's own projects only, listing each project that needs the warning,
   with its shuttle and the compact countdown from #349. Staff see the same
   alert for their own projects only; their all-projects list would
   otherwise flood.
3. Not on every page of the site. A site-wide banner belongs to the
   notifications design Tim wants done carefully (issues-05), so it is out
   of scope.

## Data and cost

- `deadline_warning()` uses the project's `shuttle` (already
  `select_related` on the list) and `submitted_file_id`, so it adds no
  queries per row.
- The list alert reuses the list's queryset filtered to the user's own
  projects, so it adds no query beyond the page's own.

## Testing

- Model: each condition (closed shuttle, no deadline, deadline passed,
  more than 14 days away, submitted, archived) gives `None`. 14 days
  minus an hour gives `"warning"` and 2 days gives `"urgent"`. The boundary
  is computed from `timezone.now()`.
- Project page: the banner and its next-step line for each state; the owner
  and staff see it; none when submitted, closed or far away.
- Projects list: the alert lists only the user's own warned projects, with
  the countdown; none when nothing qualifies; staff's alert excludes other
  users' projects.
- Browser test: an owner with a project due in 2 days sees the red banner
  with a running countdown on the project page, and the alert on
  `/projects/`.

## Open questions for the coordinator (defaults in brackets)

1. Thresholds [14 days warning, 3 days urgent].
2. Also warn when a file *is* submitted but a newer revision is waiting to be
   submitted [no: submitted means the owner has acted; #285 and later items
   can revisit].
