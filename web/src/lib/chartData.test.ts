import { describe, expect, it } from 'vitest'
import type { PricePoint } from '../api/types'
import { dayStarts, hourTicks, toChartRows } from './chartData'
import { addDays, formatTime, helsinkiDate } from './time'

// Tests run with TZ=America/New_York (vite.config.ts); output must still be Helsinki time.
function quarters(startIso: string, count: number, price = (i: number) => String(i)): PricePoint[] {
  const start = Date.parse(startIso)
  return Array.from({ length: count }, (_, i) => ({
    start: new Date(start + i * 900_000).toISOString(),
    end: new Date(start + (i + 1) * 900_000).toISOString(),
    resolution_minutes: 15,
    price_c_kwh: price(i),
  }))
}

describe('time helpers', () => {
  it('formats in Helsinki time, not the computer timezone', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/New_York')
    expect(formatTime('2025-11-14T22:00:00Z')).toBe('00:00') // UTC+2 in November
    expect(formatTime('2025-07-01T21:00:00Z')).toBe('00:00') // UTC+3 in summer
  })

  it('gives the Helsinki date even when it is still yesterday elsewhere', () => {
    expect(helsinkiDate(new Date('2025-11-14T23:30:00Z'))).toBe('2025-11-15')
  })

  it('adds calendar days across month ends and DST', () => {
    expect(addDays('2025-10-31', 1)).toBe('2025-11-01')
    expect(addDays('2025-10-25', 1)).toBe('2025-10-26')
  })
})

describe('toChartRows', () => {
  const prices = quarters('2025-11-14T22:00:00Z', 8, (i) => (i === 3 ? '-1.5' : `${i}.25`))

  it('converts prices to numbers and labels in Helsinki time', () => {
    const rows = toChartRows(prices, new Date('2020-01-01'), [])
    expect(rows[0]).toMatchObject({ time: '00:00', day: '2025-11-15', price: 0.25 })
    expect(rows[3].price).toBe(-1.5)
  })

  it('marks the slot that contains "now"', () => {
    const rows = toChartRows(prices, new Date('2025-11-14T22:20:00Z'), [])
    expect(rows.filter((r) => r.isCurrent).map((r) => r.time)).toEqual(['00:15'])
  })

  it('marks slots inside the cheapest window only', () => {
    const window = { start: '2025-11-15T00:30:00+02:00', end: '2025-11-15T01:00:00+02:00' }
    const rows = toChartRows(prices, new Date('2020-01-01'), [window])
    expect(rows.filter((r) => r.inCheapest).map((r) => r.time)).toEqual(['00:30', '00:45'])
  })

  it('finds 3-hourly ticks and day boundaries', () => {
    const twoDays = quarters('2025-11-14T22:00:00Z', 192)
    const rows = toChartRows(twoDays, new Date('2020-01-01'), [])
    expect(hourTicks(rows).map(formatTime)).toEqual([
      '00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00',
      '00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00',
    ])
    expect(dayStarts(rows).map((r) => r.day)).toEqual(['2025-11-16'])
  })
})
