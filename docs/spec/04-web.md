# 04 · Web app

The rider-facing product. Next.js (App Router), TypeScript in strict mode, Tailwind CSS, deployed on Vercel. Most riders will open it on a phone at a bus stop, so it is designed for a small screen, one hand, and a weak connection.

## 1. Principles

1. **Answer first.** The line page opens with one sentence: "Line 720 ran 95% of its scheduled trips over the past 28 days." Charts come after.
2. **Mobile first.** Design at 360 px wide; scale up. Touch targets at least 44 px.
3. **Plain language.** "Trips that never ran", not "missed-trip rate". Define each term once, with a link to the method page.
4. **Honest numbers.** Show the range next to each rate. Show "not enough data" for suppressed cells, never a zero.
5. **Fast.** Public pages render on the server and are cached; JavaScript is only loaded where interaction needs it.
6. **No third-party trackers.** No ad or analytics scripts that set cookies.

## 2. Stack

| Concern | Choice |
| --- | --- |
| Framework | Next.js, App Router, React Server Components for public pages |
| Language | TypeScript 5.9, `strict: true` plus `noUncheckedIndexedAccess`, no `any`. TypeScript 7 (the native compiler) waits until typescript-eslint and openapi-typescript support it; both cap at 5.x or 6.0 today |
| Styles | Tailwind CSS; design tokens as CSS variables; light and dark themes |
| API client | Types generated from the committed `services/api/openapi.json` into `web/lib/api/schema.ts` (`openapi-typescript`, `make openapi`); CI regenerates and fails on a diff. `lib/api/client.ts` is one typed `apiGet(path, {params, query})`: a missing path parameter or an unknown query parameter is a compile error. Never hand-write response types |
| Server data | `fetch` in server components with `revalidate: 300` |
| Client data (account pages) | TanStack Query |
| Forms | React Hook Form with Zod schemas |
| Charts | Hand-built SVG heatmap; Recharts for the trend line |
| Tests | Vitest and React Testing Library; Playwright for end-to-end |
| Lint and format | ESLint, Prettier, `tsc --noEmit` in CI |

## 3. Routes

| Route | Purpose | Rendering |
| --- | --- | --- |
| `/` | Line search, headline number, count of trips announced as canceled right now, call to action "Get alerts for your commute". Until M5 validates the system numbers against Metro's report (API spec section 4.1), the headline number is left out; the alerts call to action arrives with M3 | Server, per request (API responses cached 60 s) |
| `/lines` | All lines, sortable by reliability (least reliable first; lines without enough data last, never ranked as 0); search by number prefix. Plain links and a GET form | Server, per request (`searchParams`; API response cached 300 s) |
| `/lines/[line]` (`[line]` is the line slug, ADR-028: `/lines/10-48`) | Summary sentence, direction switch, hour × day-type heatmap, 12-week trend, current announced cancellations, "Get alerts for this line" | Server, cached; one statically generated page per line |
| `/lines/[line]/stops/[stopId]` (P1) | Reliability at one stop; next scheduled trips with announced cancellations flagged | Server, cached |
| `/alerts/new` | Three-step commute builder: line and direction, stop, days and time window; then email | Client |
| `/auth/verify` | Reads the token from the URL fragment, posts it, redirects | Client |
| `/account` | Commutes (pause, edit, delete), alert history, delete account | Client, session required |
| `/findings` (P1) | Three findings, each with a chart, an interval, and a method note | Server, cached |
| `/method` | How trips are classified, in plain words; thresholds in force; limitations | Server, per request (API response cached 300 s) |
| `/data` | Dataset downloads, API docs link, attribution | Server, cached |
| `/status` | How completely the archive captured each feed, per Los Angeles day over the past 7 days (a gap can be ours or Metro's; days cut by the window are marked partial; padding buckets are never published), last data refresh. Uptime comes with the M4 monitoring | Server, per request (API response cached 60 s) |
| `/privacy`, `/about` | What is stored and why; who built it; "not affiliated with LA Metro" | Static |

Pages without route parameters render per request rather than at build time, so a web build never needs the API (a VM outage must not block a web deploy). Line pages are generated on first request (ISR). Measured 2026-11-19 on a production build: 8 page loads across home, method, status and lines made 3 API requests, so the fetch `revalidate` cache holds under `force-dynamic`. Each page view is still a server render (no CDN-cached HTML) — the trade-off for build independence. Every page has the four states: `app/loading.tsx` while rendering, an empty message, `app/error.tsx` with retry, and `StaleNotice` once `data_as_of` is over an hour old.

Line pages are the search-engine entry point ("is the 720 bus reliable"). Give each a specific title, description, and Open Graph image with the line's headline number.

## 4. Key components

- **`ReliabilityHeatmap`**: 24 hours × 3 day types. Color encodes the share of trips that never ran; each cell is a focusable element with a text label ("Weekdays, 5 PM: 5% of 412 trips never ran, range 4 to 7%"). Suppressed cells are hatched and labeled "not enough data". Includes a "view as table" toggle.
- **`TrendChart`**: weekly announced and unplanned rates, stacked.
- **`CancellationList`**: currently announced cancellations, soonest first, with how far ahead each was announced ("announced 1 h 10 min before departure", or "announced after departure"; ADR-029), the data's `as_of`, a stale warning when the API flags it, and "unavailable" (never an empty list) when it can't load.
- **`LikelyMissingList`** (P1): trips flagged likely missing right now, on the home page and each line page. Labeled "our estimate", with the detector's measured precision and a link to the method page. Never mixed into the announced list.
- **`LinePicker`**, **`StopPicker`**: type-ahead for lines; stops in route order for the chosen direction, with a "use my location" option that never sends coordinates to the server (nearest stop is computed in the browser).
- **`TimeWindowPicker`**: days of week and a start and end time; shows "about N trips are scheduled in this window".
- **`CommuteCard`**: label, line, stop, window, 28-day reliability, pause switch.

Every component that shows data handles four states: loading (skeleton), empty, error (with retry), and stale (`data_as_of` older than 60 minutes shows a notice).

## 5. Commute builder flow

1. Pick a line and direction (headsign shown, not "direction 0").
2. Pick the boarding stop.
3. Pick days and a time window. Show scheduled trips in that window so the rider can confirm.
4. Enter an email. "We'll send a link to confirm. No password."
5. After verification, the commute is created and the rider lands on `/account` with a confirmation and the next scheduled trip.

The unfinished commute is kept in `sessionStorage` (wrapped in try/catch) through the email step, so the rider doesn't re-enter it after clicking the link on the same device. If the link opens on another device, the rider lands on `/alerts/new` signed in and fills the form again. Don't build a server-side draft for this in v1.

## 6. Accessibility (WCAG 2.2 AA)

- Color is never the only signal: heatmap cells have text labels and a table view.
- Contrast at least 4.5:1 for text in both themes.
- Full keyboard operation; visible focus; logical heading order; form errors announced and tied to their fields.
- `prefers-reduced-motion` respected.
- Automated checks with axe in Playwright on every page; manual screen-reader pass on the commute builder in M5.

## 7. Performance budgets

| Measure | Budget (line page, mid-range phone, slow 4G) |
| --- | --- |
| Largest Contentful Paint | ≤ 2.5 s |
| Cumulative Layout Shift | ≤ 0.1 |
| Interaction to Next Paint | ≤ 200 ms |
| JavaScript shipped on public pages | ≤ 120 KB compressed |
| Lighthouse performance and accessibility | ≥ 90 |

Lighthouse CI runs on every PR against the Vercel preview and fails the build under budget.

**Measured 2026-11-19 (PR #54, production build, `next start`):** the line page loads 8 scripts, 179 KB gzip. About 1.2 KB is this app's code; the rest is the Next.js 16 and React 19 runtime that every App Router page loads, even one with no client components. The 120 KB budget can't be met with the stack this spec chooses. That is an open question for the owner (SPEC section 10), to be decided before the M5 Lighthouse gate.

## 8. Measurement without tracking

- Product counts come from the database: signups, active commutes, alerts sent, unsubscribes.
- Page views use a cookie-less, aggregate-only counter (`VERIFY` the hosting platform's built-in analytics terms; otherwise a tiny first-party endpoint that increments daily counters and stores no identifiers).
- A one-question feedback link in alert emails ("Was this alert useful? Yes / No") opens a small page that posts to `POST /v1/alerts/feedback` (P1; API spec, section 4.3).

## 9. Internationalization (P2)

Structure copy for translation from the start: no hard-coded strings in components; all text in message files. If Spanish ships, it covers the UI, alert emails, and the method page, and a fluent speaker reviews it before launch.

## 10. Tests

- **Unit and component:** heatmap labels and suppressed cells; pickers; form validation; time formatting in `America/Los_Angeles` regardless of the viewer's timezone.
- **End-to-end (Playwright, against a local stack with seeded data and the file email adapter):**
  1. Find a line and read its reliability
  2. Build a commute, confirm by email link, see it in the account
  3. Receive an alert for a seeded cancellation, unsubscribe with one click
  4. Delete the account
- **Visual check** at 360 px and 1280 px for the line page.

## 11. Layout (`web/`)

```text
web/
├── app/                 # routes (see section 3)
├── components/          # ui/ (buttons, inputs), charts/, commute/, layout/
├── lib/                 # api client (generated), time.ts, format.ts
├── messages/            # en.json (es.json if P2)
├── tests/  e2e/
└── next.config.ts  tailwind.config.ts  tsconfig.json
```
