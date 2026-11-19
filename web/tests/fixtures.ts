/** Response fixtures typed by the generated schema, so they break when the API changes. */
import type { Schemas } from "@/lib/api/client";

export const RATES: Schemas["Rates"] = {
  n_scheduled: 1240, n_unknown: 12, n_ran: 1150, n_partial: 20, n_missed: 58,
  n_missed_announced: 30, n_missed_unplanned: 28, n_trips: 1228, n_service_days: 17,
  missed_rate: 0.0472, announced_rate: 0.0244, unplanned_rate: 0.0228, unplanned_share: 0.4828,
  missed_rate_ci_low: 0.0381, missed_rate_ci_high: 0.0569, unplanned_share_ci_low: 0.3621,
  unplanned_share_ci_high: 0.6034, suppressed: false,
}; // prettier-ignore

export const SUPPRESSED: Schemas["Rates"] = {
  ...RATES, missed_rate: null, announced_rate: null, unplanned_rate: null, unplanned_share: null,
  missed_rate_ci_low: null, missed_rate_ci_high: null, unplanned_share_ci_low: null,
  unplanned_share_ci_high: null, suppressed: true,
}; // prettier-ignore

export function cell(overrides: Partial<Schemas["ReliabilityCell"]>): Schemas["ReliabilityCell"] {
  return {
    day_type: "weekday", hour_local: 17, n_trips: 412, missed_rate: 0.051,
    announced_rate: 0.024, unplanned_rate: 0.027, ci_low: 0.038, ci_high: 0.066,
    suppressed: false, ...overrides,
  }; // prettier-ignore
}

export const DETAIL: Schemas["LineDetail"] = {
  line: "720", line_slug: "720", display_name: "720", line_kind: "Metro Rapid Line",
  description: null, route_color: null, route_text_color: null, window: "28d",
  data_through: "2026-12-01", data_as_of: "2026-12-01T17:40:12Z", summary: RATES,
  directions: [
    { direction_id: 0, headsign: "Santa Monica", first_stop_name: null, last_stop_name: null, summary: RATES },
    { direction_id: 1, headsign: "Commerce", first_stop_name: null, last_stop_name: null, summary: RATES },
  ],
}; // prettier-ignore

export const CANCELLATIONS: Schemas["CurrentCancellations"] = {
  as_of: "2026-12-01T17:38:00Z", stale: false, data_as_of: "2026-12-01T17:40:12Z",
  cancellations: [{
    service_date: "2026-12-01", trip_id: "T1", line: "720", line_slug: "720",
    display_name: "720", direction_id: 0, headsign: "Santa Monica",
    sched_start: "2026-12-01T18:30:00Z", sched_start_local: "10:30",
    first_seen_at: "2026-12-01T17:20:00Z", advance_notice_s: 4200,
  }],
}; // prettier-ignore
