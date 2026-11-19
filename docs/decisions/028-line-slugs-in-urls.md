# ADR-028: Lines are identified in URLs by a slug

- **Status:** Accepted
- **Date:** 2026-11-19
- **Supersedes:** API spec section 1's "A line is identified by its public number as a string (`"720"`)" for URL paths. The `line` field in responses is unchanged.
- **Evidence:** the schedule version in force (`dim_line`, 114 lines) has 8 combined lines with a slash (`10/48`, `14/37`, `35/38`, `211/215`, `235/236`, `242/243`, `260/261`, `487/489`) and 6 named services with spaces and punctuation (`Dodger Stadium Express`, `LAX / Metro Transit Center -  SoFi Stadium Express`, …). Slugs computed for all 114 are distinct.

## Context

`GET /v1/lines/{line}/reliability` puts the line in a path segment, and the web app does the same (`/lines/[line]`). A slash can't appear in a path segment. Encoding it as `%2F` doesn't help: the web framework decodes it before routing, so `/v1/lines/10%2F48/reliability` doesn't match the route. Spaces and slashes in names also make URLs that are awkward to share.

## Decision

1. Every line gets `line_slug`, computed once in dbt (`dim_line`):
   - lowercase;
   - every run of characters other than letters and digits becomes one hyphen;
   - leading and trailing hyphens are trimmed.

   So `720` stays `720`, `10/48` becomes `10-48`, and `Dodger Stadium Express` becomes `dodger-stadium-express`.
2. URL paths use the slug: `/v1/lines/10-48/reliability`, `/lines/10-48`. The API resolves slug → line through `serving.line`, and every response carries `line` (Metro's name), `line_slug` and `display_name`.
3. Tests: the slug is unique within a schedule version, and one-to-one with `line` across all versions, so a bookmarked URL can never come to mean a different line.

## Why

Numbered lines, nearly all of them, keep exactly the URL the spec described, so `/lines/720` still works. The few awkward names get readable, stable URLs. Computing the slug in dbt puts it in one place, next to the line it names, and the tests catch a future collision when a new schedule loads, not when a rider's link breaks.

## Alternatives considered

- **Encode the line in the path:** breaks on `/`, because frameworks decode `%2F` before routing.
- **Query parameter (`/v1/line/reliability?line=10/48`):** works, but loses clean, cacheable resource URLs and departs further from the spec.
- **route_id (`10-13201`):** stable within a schedule but carries Metro's service-change tag, so it changes at every service change, and it isn't what riders know.

## Consequences

- If Metro ever names two lines so their slugs collide, the dbt test fails the build and an ADR decides the tie-break.
- If Metro renames a line, its slug changes with it, so old links 404. Acceptable for a rename. A redirect table can come later if it ever matters.

## Would change if

- Metro adopts stable line IDs in GTFS (`route_short_name` without slashes, or a network ID): use those.
