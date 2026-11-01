// Turn API prices into rows for the chart (and the table view).
import type { PricePoint } from '../api/types'
import { formatDay, formatTime, helsinkiDate } from './time'

export interface TimeWindow {
  start: string
  end: string
}

export interface ChartRow {
  start: string
  end: string
  time: string // "14:45", Helsinki
  day: string // YYYY-MM-DD, Helsinki
  dayLabel: string // "Sat 15 Nov"
  price: number // c/kWh
  isCurrent: boolean
  inCheapest: boolean
}

export function toChartRows(prices: PricePoint[], now: Date, windows: TimeWindow[]): ChartRow[] {
  const nowMs = now.getTime()
  const spans = windows.map((w) => [Date.parse(w.start), Date.parse(w.end)] as const)
  return prices.map((p) => {
    const start = Date.parse(p.start)
    const end = Date.parse(p.end)
    return {
      start: p.start,
      end: p.end,
      time: formatTime(p.start),
      day: helsinkiDate(new Date(p.start)),
      dayLabel: formatDay(p.start),
      price: Number(p.price_c_kwh),
      isCurrent: start <= nowMs && nowMs < end,
      inCheapest: spans.some(([ws, we]) => start >= ws && end <= we),
    }
  })
}

/** Axis ticks: every 3 hours on the hour, so labels never collide on a phone. */
export function hourTicks(rows: ChartRow[], everyHours = 3): string[] {
  return rows
    .filter((r) => r.time.endsWith(':00') && Number(r.time.slice(0, 2)) % everyHours === 0)
    .map((r) => r.start)
}

/** Where a new day starts in the data (for the "Tomorrow" divider). */
export function dayStarts(rows: ChartRow[]): ChartRow[] {
  return rows.filter((r, i) => i > 0 && r.day !== rows[i - 1].day)
}
