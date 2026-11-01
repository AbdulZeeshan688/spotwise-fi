// All times are shown in Finnish time, whatever timezone the user's computer is in.
export const TZ = 'Europe/Helsinki'

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})
const dayFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ,
  weekday: 'short',
  day: 'numeric',
  month: 'short',
})
// en-CA formats dates as YYYY-MM-DD
const isoDateFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** "14:45" in Helsinki time. */
export function formatTime(value: string | Date): string {
  return timeFormat.format(new Date(value))
}

/** "Sat 15 Nov" in Helsinki time. */
export function formatDay(value: string | Date): string {
  return dayFormat.format(new Date(value))
}

/** The Helsinki calendar date of a moment, as YYYY-MM-DD. */
export function helsinkiDate(value: Date): string {
  return isoDateFormat.format(value)
}

/** Add days to a YYYY-MM-DD date (calendar math, no timezone involved). */
export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** Format a c/kWh string or number with 2 decimals. */
export function formatPrice(value: string | number): string {
  return Number(value).toFixed(2)
}
