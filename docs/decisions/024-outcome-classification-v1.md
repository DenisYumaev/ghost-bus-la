# ADR-024: Outcome classification v1 (M1): `partial` included, updates-only trips are partial

- **Status:** Accepted
- **Date:** 2026-11-17
- **Supersedes:** `docs/SPEC.md` M1's outcome list ("`ran`, `missed`, `unknown`"); M1 now also builds `partial`. The decision table in pipeline spec section 8 is unchanged; this ADR fixes how its inputs are computed in v1 and which rows M1 builds
- **Evidence:** `docs/research/observations.md` (service date 2026-11-15: 121 trips both observed running and canceled, 76 of them with positions after the start and median progress 0.21; 105 trips observed only through trip updates); `stg_fetch_log` (feed timestamp age at fetch: median 10–13 s, max 98 s)

## Context

M1 planned three outcomes: `ran`, `missed`, `unknown`. Section 8's decision table also has `partial` (observed, coverage under 0.80) and `likely_untracked` (not observed, but both block neighbours seen with the same vehicle). Real data showed a three-outcome table can't be honest: trips that ran a fifth of their route and were then canceled would all be `ran`. It also showed a case the spec didn't settle: trips with a vehicle assigned in trip updates but no vehicle positions, which have no coverage to compare with 0.80.

## Decision

1. **M1 builds rules 1, 2, 3 and 5 of section 8**, in order: `ran` (observed, coverage ≥ `min_stop_coverage`), `partial` (observed, coverage below it or unknown), `unknown` (not observed, feed-healthy share < `min_feed_healthy_share`), `missed` (everything else). Rule 4 (`likely_untracked`) needs `int_block_neighbors` and comes in M4.
2. **Coverage** = furthest `current_stop_sequence` reported by a matched vehicle position ÷ the trip's stop count. Metro's stop sequences run 1..n (enforced by a test), so this is a share of stops.
3. **A trip observed only through trip updates is `partial`.** It has no position, so no coverage, and claiming `ran` without position evidence would overstate service. `partial` is reported separately and never counted as missed (section 8).
4. **Feed health:** a feed is healthy in a 5-minute bucket if at least one fetch in it succeeded (`written` or `duplicate`) with a feed timestamp under `feed_fresh_max_s` (180 s) old. A trip's feed-healthy share is the share of 5-minute buckets overlapping its observation window in which *both* realtime feeds were healthy.
5. **`is_metro_operated` is NULL in v1.** `seed_contracted_lines` arrives with the headline metrics (M5).
6. **Announcement:** `announced = rt_canceled` (canceled and not reinstated before the scheduled start), `announce_source = 'trip_updates'`, `advance_notice_s` = scheduled start − `first_seen_at` of the final cancellation episode (negative when announced late).

## Why

The point of the outcome table is that every number traces to a defensible label. A bus that ran 20% of a route and was then canceled didn't provide the trip, and calling it `ran` would flatter service. Section 8 already has the right label, so the cost of building it now is one CASE branch and a unit test. Updates-only trips are the opposite risk: we know a vehicle was assigned, but not that it moved, so the conservative label is the one that doesn't claim service we can't see and doesn't count it as missed either. Deferring rule 4 keeps M1 small. Its absence biases `missed` upward, which is the safe direction while nothing is published (M5 validates against Metro's report first).

## Alternatives considered

- **Keep M1 at three outcomes.** Simplest, but 121 trips on one day would be mislabeled `ran`.
- **Updates-only trips as `ran`.** Matches "observed running" literally, but treats an assigned vehicle as proof of service.
- **Updates-only trips as `unknown`.** Honest about the missing coverage, but `unknown` means "feeds were down", and these trips had a live trip-update stream, so it would muddy the feed-health signal.
- **Build `likely_untracked` now.** Needs block neighbours (M4's scope); not needed to answer M1's acceptance query.

## Consequences

- `fct_trip_outcomes` outcomes in M1: `ran`, `partial`, `unknown`, `missed`. The reconciliation identity (scheduled = sum of outcomes) holds with `likely_untracked` = 0.
- M1's `missed` includes trips M4 may reclassify as `likely_untracked`; don't quote M1 missed rates.
- Thresholds (0.80, 0.90, 180 s, the −30/+60 min window) are dbt vars, to be tuned against hand-checked trips and frozen in a later ADR.

## Would change if

- Hand-checked trips show updates-only trips usually ran in full: then they become `ran`, or coverage comes from trip-update stop progress.
- M4's block-neighbour rule lands: rule 4 slots in between rules 3 and 5.
