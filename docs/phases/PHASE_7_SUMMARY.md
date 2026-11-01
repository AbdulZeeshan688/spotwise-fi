# Phase 7 — Web app: summary

Requirements: UI-01 … UI-05.

## What was built (`web/`)
- **Vite 8 + React 19 + TypeScript 7, `strict: true`**, scaffolded with the official `create-vite` React-TS template. Recharts for the chart; Vitest + Testing Library + jsdom for tests. Plain CSS with design tokens (no CSS framework).
- **Typed API client** (`src/api/types.ts`, `client.ts`): interfaces that mirror the FastAPI/Pydantic response models, `getPrices`, `getCheapestWindow` (returns `null` for "not published"), `getQuality`, and `streamChat`. `streamChat` reads the SSE stream from a `fetch` POST, because `EventSource` only supports GET. FastAPI's `detail` messages become `ApiError(status, message)`.
- **Chart (UI-01)** (`PriceChart.tsx`): 15-minute bars for today + tomorrow, an **Hourly** toggle (uses the API's `resolution=60`), and an **Incl./Excl. VAT** toggle. The **current slot** is orange with a "Now" line, the **cheapest 3-hour window** is aqua, and a dashed divider marks where tomorrow starts. Tooltip on hover, a text summary above the chart ("Now", "Cheapest 3 h"), and a **"Show prices as a table"** view.
- **Chat (UI-02)** (`ChatPanel.tsx`): streams tokens, shows "Checking prices…" while tools run, keeps the `session_id` for memory, has 4 example-question chips, and shows a ⚠ note when the number guardrail flagged the answer. Friendly messages for 429 (rate limit), 503 (no LLM configured) and network errors.
- **Quality badge (UI-03)** (`QualityBadge.tsx`): green/yellow/red/unknown from `/quality/latest`, always with an icon and a word (✓ Data OK / ! Data: check / ✕ Data problem), with failing checks in the tooltip.
- **Mobile, keyboard, dark mode (UI-04)**: one column on phones and two from 900 px. Every control is a real `<button>`/`<input>` with labels and visible focus rings; toggles use `aria-pressed`; the chat log is `aria-live`. Dark mode has its own colour steps (not an automatic invert).
- **CI (OPS-02)**: a new `frontend` job runs lint (oxlint), Vitest, and type check + build.

## Decisions (and why)
- **Times always in Helsinki** via `Intl.DateTimeFormat({ timeZone: 'Europe/Helsinki' })`. Tests run with `TZ=America/New_York` to prove a laptop in another timezone still sees Finnish times.
- **Colours were validated, not picked by eye.** I used the data-viz palette checker: blue (price), aqua (cheapest) and orange (now) pass the colour-blindness and contrast checks in both light and dark mode. Aqua is just under 3:1 contrast on the light background, which is why the text summary and the table view exist; colour is never the only signal.
- **Phones get 6-hour axis labels** (3-hour on wider screens). Seen in a 390 px screenshot: 3-hourly labels collided.
- **The final answer replaces the streamed text** when `done` arrives, so what stays on screen is exactly what the guardrail checked.
- **No routing library or state library.** One page with React state is enough.
- **Bundle is ~590 kB (~177 kB gzipped)**, mostly Recharts. Fine for v1; code-splitting the chart is a possible Phase 8 improvement.

## Verified
- `npm test`: **21 tests pass** (time helpers in another timezone, chart transform, ticks/day boundaries, API client incl. SSE split across network chunks and error handling, chat panel streaming/session/guardrail warning/429, quality badge).
- `tsc -b` (strict), `oxlint`, `vite build`: clean.
- **Real app** against the real API and today's porssisahko data, screenshotted with headless Chrome: desktop light, desktop dark (emulated `prefers-color-scheme: dark`) and a true 390 px phone layout (no horizontal scroll). Two problems found and fixed this way: the tomorrow divider label was cut off at the edge, and axis labels collided on phones.
- **Chat works with the free rule agent** (the default), streamed word by word like the LLM version.

## Learn this (interview)
- **React state for streaming:** each event updates one message by id (`setMessages(all => all.map(...))`). The functional update means no event is lost when several arrive quickly.
- **Typed API client:** the TypeScript interfaces mirror the backend's Pydantic models, so a renamed field breaks the build, not the user. Decimal prices arrive as strings and are converted only for display.
- **Timezones in the browser:** `new Date()` is an instant and the browser's own timezone is irrelevant; we always format with an explicit `timeZone`. Calendar math (`addDays`) is done on plain dates in UTC, so DST can't shift a day.
- **SSE over POST:** `EventSource` can't POST a body, so we read `response.body` with a stream reader and split on blank lines. Test: events split across network chunks still parse.
