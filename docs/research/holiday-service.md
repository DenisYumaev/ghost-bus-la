# How Metro's schedule encodes holidays

- **Date:** 2026-11-17
- **Question:** On a holiday, does the schedule switch to another day's service? If so, should reliability cells take a service date's day type from the schedule rather than the calendar? (`int_service_day_types`, PR #39)
- **Source:** the schedule version in force, `cb1a2283abecc0af` (first stored 2026-11-15), as loaded into the local warehouse. Script: `scripts/research_holiday_service.py`.

## Result

Every date where `calendar_dates.txt` adds Sunday service:

| Date | Weekday | `…_Weekday` IDs removed | `…_Sunday` IDs added | All removed | All added |
| --- | --- | --- | --- | --- | --- |
| 2026-07-04 | Saturday | 0 | 12 | 12 | 14 |
| 2026-09-07 | Monday (Labor Day) | 12 | 12 | 88 | 14 |
| 2026-11-26 | Thursday (Thanksgiving) | 12 | 12 | 88 | 12 |

`calendar.txt` has no mixed weekly patterns: none combine a weekday with a weekend day, or Saturday with Sunday.

## What it means

- On a holiday, Metro removes the day's own service and runs Sunday service. Thanksgiving removes all 12 weekday service IDs (one per division) and 76 other weekday services, and adds the 12 Sunday ones.
- So the majority of a holiday's scheduled trips come from Sunday patterns, and `int_service_day_types` classifies it `sunday`. A calendar-based day type would put Thanksgiving's Sunday-service trips into weekday cells.
- The rule needs no holiday list: a new schedule's holidays are classified the same way, as long as Metro keeps encoding them like this. The warning test `calendar_has_no_mixed_patterns` flags a schedule that introduces mixed patterns, which wouldn't vote.
