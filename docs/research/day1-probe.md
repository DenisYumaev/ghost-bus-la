# Day-1 probe: what LA Metro's data sources actually do

Run on Wednesday, November 11, 2026, between 8:18 and 8:25 p.m. Pacific, from a browser against the live services. One evening's snapshot: every count below is what was seen in that window, not a long-run average.

## Summary

| Question | Answer |
| --- | --- |
| Is realtime data available without a key? | **Yes, but only over WebSocket.** The REST realtime endpoints return empty lists |
| Format? | JSON, one message per vehicle or per trip. No protobuf on this API |
| Is the canceled-service API usable? | **No.** Its summary was last updated on 2022-10-04 and its detail endpoints return HTTP 500 |
| Are cancellations announced anywhere else? | **Yes.** The trip-updates stream marks trips `CANCELED`, including trips hours in the future |
| Do realtime trip IDs match the GTFS schedule? | **Yes, exactly.** 64 of 64 sampled IDs, including 14 canceled trips |
| Does realtime carry the service date? | Yes: `startDate` and `startTime` on every trip |
| Does the schedule have `block_id`? | Yes, on all but 713 of 33,614 trips |
| When is the next service change? | The schedule's `feed_end_date` is 2026-12-12, so expect it on **Dec 13** |
| Is there a service-alert text feed? | No. The API offers only vehicle positions and trip updates |
| Do contracted lines appear? | Yes: 10 of the 15 are in the schedule, and at least 9 showed live vehicles |

## 1. Metro API (`https://api.metro.net`)

A FastAPI service. Its OpenAPI document lists 31 paths in five groups. Agency IDs are `LACMTA` (bus) and `LACMTA_Rail`. No key was needed for anything tested.

### 1.1 Realtime over REST: empty

`GET /LACMTA/trip_detail/route_code/{route_code}` returned `[]` for routes 720, 2, 4, and `all`, while those lines were running. `GET /LACMTA/trip_detail/vehicle/{vehicle_id}` returned `[]` for a vehicle that was live on the WebSocket. Don't build on these.

### 1.2 Realtime over WebSocket: works

`wss://api.metro.net/ws/LACMTA/{endpoint}` and `wss://api.metro.net/ws/LACMTA/{endpoint}/{route_codes}`, where `endpoint` is `vehicle_positions` or `trip_updates` and `route_codes` is an optional comma-separated filter. The API's own description says updates are sent every 3 seconds. In practice the server re-sends the whole fleet in a loop, one JSON message per entity.

**Vehicle positions** (all routes, 12 seconds):

- 4,581 messages, 1.39 MB; 1,529 distinct vehicles; about 3 full cycles, so roughly 0.46 MB per cycle
- 620 distinct trips on 105 route codes; about 40% of vehicles carried a trip, the rest were parked or out of service
- Vehicle timestamps lagged a median of 22 seconds, worst case 598 seconds

```json
{"id": "9504", "vehicle": {"trip": {"tripId": "10720013711947-JUNE26", "startTime": "19:47:00",
 "startDate": "20261111", "scheduleRelationship": "SCHEDULED", "routeId": "720-13201", "directionId": 0},
 "position": {"latitude": 34.067894, "longitude": -118.42581, "bearing": 82.0, "speed": 6.169152},
 "currentStopSequence": 13, "currentStatus": "IN_TRANSIT_TO", "timestamp": "1794457037",
 "stopId": "6063", "vehicle": {"id": "9504", "label": "9504"}}, "route_code": "720"}
```

A vehicle with no trip has only `position`, `timestamp`, and `vehicle`, and an empty `route_code`.

**Trip updates** (all routes, 20 seconds):

- 19,516 messages, 21.3 MB; 3,254 distinct trips; about 6 full cycles, so roughly 3.5 MB per cycle
- Trips for two service dates at once: 985 for 2026-11-11 and 2,269 for 2026-11-12. The stream lists tomorrow's trips too
- 731 trips had a vehicle assigned. Of 455 trips still to start that evening, 234 had no vehicle yet
- 22 trips had `scheduleRelationship: "CANCELED"`. Of 23,997 stop-time updates, 4,473 were `SKIPPED`
- `route_code` is empty on trip-update messages; use `trip.routeId`

```json
{"id": "10212002392028-JUNE26", "tripUpdate": {"trip": {"tripId": "10212002392028-JUNE26",
 "startTime": "20:28:00", "startDate": "20261111", "scheduleRelationship": "CANCELED",
 "routeId": "212-13201", "directionId": 1}, "timestamp": "1794457342"}, "route_code": ""}
```

### 1.3 Cancellations in the trip-updates stream

At 8:22 p.m. the 22 canceled trips had scheduled starts from 6:12 p.m. to 11:04 p.m. the same day:

- Eight were still in the future, the furthest 2 hours 42 minutes ahead. So at least some cancellations are announced hours in advance
- Fourteen had start times already past. Canceled entries stay in the stream after the trip's time
- Canceled trips carry no stop-time updates
- Lines seen: 2, 4, 33, 40, 53, 60, 90, 92, 115, 117, 204, 210, 212, 224, 233

Not yet known: how early a cancellation first appears (needs the archive), when entries leave the stream, and what kinds of cancellation Metro marks this way.

### 1.4 Canceled-service REST API: dead

- `GET /canceled_service_summary` returns counts per line with `"last_updated": "2022-10-04 15:56"`
- `GET /canceled_service/all` and `GET /canceled_service/line/720` return HTTP 500

Metro's documentation says this API lists scheduled cancellations only and excludes contracted lines. Those statements describe this dead API. Whether they hold for the `CANCELED` flag in the realtime stream is unknown.

### 1.5 The API's own static endpoints: stale

`/LACMTA/trips/{trip_id}` and `/LACMTA/stop_times/trip_id/{trip_id}` returned `[]` for a trip that was live. `/calendar_dates` and `/LACMTA/route_stops/720` hold `DEC25` service IDs and route ID `720-13172`, while the live stream uses `720-13201` and `JUNE26`. Take the schedule from GitLab, never from this API.

## 2. GTFS static (`https://gitlab.com/LACMTA/gtfs_bus`)

The repo holds `gtfs_bus.zip` (22.2 MB), `feed_info.txt`, and a README with an update log. The individual tables exist only inside the ZIP.

| File | Rows or size | Notes |
| --- | --- | --- |
| `feed_info.txt` | 1 | `feed_start_date` 2026-06-07, `feed_end_date` 2026-12-12; `feed_version` is empty |
| `trips.txt` | 33,614 | Columns: `route_id, service_id, trip_id, trip_headsign, direction_id, block_id, shape_id, trip_id_event` |
| `stop_times.txt` | 2,106,179; 307 MB unzipped | Extra columns: `stop_headsign, trip_id_event, route_code, destination_code, timepoint, bay_num` |
| `routes.txt` | 114 | Route IDs look like `720-13201` |
| `stops.txt` | 11,892 | |
| `calendar.txt` | 129 | Service IDs look like `JUNE26-D01CAR-1_Weekday` |
| `calendar_dates.txt` | 7,086 | Holidays swap weekday service for Sunday service |
| `shapes.txt` | 18 MB | |

Details that affect the build:

- **Trip IDs** look like `10720013711947-JUNE26`. 32,607 carry the `JUNE26` tag; about 1,000 are special-event trips with other formats (stadium and arena shuttles)
- **`trip_headsign` is empty on every trip.** Take the rider-facing destination from `stop_headsign` or `destination_code` in `stop_times.txt`
- **`block_id`:** 2,280 distinct blocks; 713 trips have none
- **Times run to 29:45.** 1,555 trips have stop times at or past 24:00:00, across 81,553 rows
- **20 rows have an hour without a leading zero** (`9:57:00`). Parse times as numbers, never compare them as text
- **Route short names aren't all numbers:** `10/48`, `14/37`, `487/489`, and names like "Dodger Stadium Express"
- **Day types:** 13,434 weekday trips, 9,639 Saturday, 9,534 Sunday, 1,007 other
- The README's last logged update is February 2, 2026, but the ZIP holds the June 2026 schedule. Detect new versions by file hash, not by the README

**Contracted lines** (from Metro's cancellation-report page): 125, 128, 167, 205, 218, 232, 266, 501, 577, and 605 are in `routes.txt`; 96, 130, 177, 256, and 603 are not. Live vehicles were seen on 125, 128, 167, 205, 218, 232, 266, 501, and 577.

## 3. What this changes in the design

1. **Ingest is a WebSocket snapshotter, not an HTTP poller.** Hold one connection per stream. Every 30 seconds (vehicle positions) or 60 seconds (trip updates), write one snapshot: the latest message per entity from one full cycle, as newline-delimited JSON, compressed. Reconnect with backoff.
2. **Sizes need measuring before cadences are final.** Uncompressed, the cycle sizes above come to about 1.3 GB a day for positions at 30 seconds and 5 GB a day for trip updates at 60 seconds. Compression should cut that several-fold; measure it over a full day in M0 and set cadences from the result.
3. **Announced cancellations come from trip updates**, not from the canceled-service API. The detector reads trip-update snapshots; the stable key is `(tripId, startDate)`; matching to commutes is exact.
4. **A canceled entry outlives its trip.** An event closes when its trip's time has passed. A cancellation is withdrawn if the trip returns to `SCHEDULED` before its start.
5. **Tomorrow's trips are in the stream**, so a cancellation announced the evening before can be alerted the evening before.
6. **Product copy can't claim what the `CANCELED` flag covers.** Say "marked canceled in Metro's realtime feed".
7. **The service change is expected on Dec 13.** It is the live test of schedule versioning.
8. **No alert-text feed exists**, so the optional LLM alert-cause feature is dropped.
9. **A second source is worth requesting.** This WebSocket is undocumented in its limits. Metro's realtime data comes from Swiftly, which offers standard GTFS-realtime with an API key. Request a key in M0 as a fallback and a cross-check; build on the WebSocket now.

## 4. Still open

- How far in advance cancellations first appear, as a distribution (needs a week of archive; decides the M1 product gate)
- When canceled entries leave the stream
- Whether the WebSocket drops or throttles long-lived connections
- What Metro's monthly cancellation report counts, and whether past months are available
- Metro's terms of use for this API and for redistributing derived data
