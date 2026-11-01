import { useSyncExternalStore } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import { dayStarts, hourTicks, type ChartRow } from '../lib/chartData'
import { formatPrice, formatTime } from '../lib/time'

interface Props {
  rows: ChartRow[]
  vat: boolean
}

const NARROW = '(max-width: 599px)'

/** True on phone-width screens (fewer axis labels there, so they don't collide). */
function useNarrowScreen(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia?.(NARROW)
      query?.addEventListener('change', onChange)
      return () => query?.removeEventListener('change', onChange)
    },
    () => window.matchMedia?.(NARROW).matches ?? false,
  )
}

function barColour(row: ChartRow): string {
  if (row.isCurrent) return 'var(--series-now)'
  if (row.inCheapest) return 'var(--series-cheap)'
  return 'var(--series-price)'
}

function PriceTooltip({ active, payload }: TooltipContentProps) {
  const row = payload?.[0]?.payload as ChartRow | undefined
  if (!active || !row) return null
  return (
    <div className="tooltip">
      <div className="tooltip__time">
        {row.dayLabel} {row.time}–{formatTime(row.end)}
      </div>
      <div className="tooltip__price">{formatPrice(row.price)} c/kWh</div>
      {row.isCurrent && <div className="tooltip__tag">Now</div>}
      {row.inCheapest && <div className="tooltip__tag">Cheapest 3 h</div>}
    </div>
  )
}

export function PriceChart({ rows, vat }: Props) {
  const narrow = useNarrowScreen()
  const current = rows.find((r) => r.isCurrent)
  const hasNegative = rows.some((r) => r.price < 0)
  return (
    <figure className="chart">
      <div
        className="chart__plot"
        role="img"
        aria-label={`Bar chart of electricity prices in c/kWh ${vat ? 'including' : 'excluding'} VAT, Finnish time. The table below has every value.`}
      >
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={rows} margin={{ top: 16, right: 8, bottom: 0, left: 0 }} barCategoryGap={1}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="start"
              ticks={hourTicks(rows, narrow ? 6 : 3)}
              tickFormatter={formatTime}
              tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
              axisLine={{ stroke: 'var(--axis)' }}
              tickLine={false}
              interval={0}
              minTickGap={8}
            />
            <YAxis
              width={44}
              tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => v.toFixed(0)}
              label={{
                value: 'c/kWh',
                angle: -90,
                position: 'insideLeft',
                fill: 'var(--text-secondary)',
                fontSize: 12,
              }}
            />
            {hasNegative && <ReferenceLine y={0} stroke="var(--axis)" />}
            {dayStarts(rows).map((r) => (
              <ReferenceLine
                key={r.start}
                x={r.start}
                stroke="var(--axis)"
                strokeDasharray="4 4"
                label={{ value: r.dayLabel, position: 'insideTopRight', fill: 'var(--text-secondary)', fontSize: 12 }}
              />
            ))}
            {current && (
              <ReferenceLine
                x={current.start}
                stroke="var(--series-now)"
                strokeWidth={2}
                label={{ value: 'Now', position: 'top', fill: 'var(--text-primary)', fontSize: 12 }}
              />
            )}
            <Tooltip content={PriceTooltip} cursor={{ fill: 'var(--hover)' }} />
            <Bar dataKey="price" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.start} fill={barColour(r)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="legend">
        <span className="legend__item">
          <span className="legend__swatch legend__swatch--price" aria-hidden="true" /> Price
        </span>
        <span className="legend__item">
          <span className="legend__swatch legend__swatch--cheap" aria-hidden="true" /> Cheapest 3 h
        </span>
        <span className="legend__item">
          <span className="legend__swatch legend__swatch--now" aria-hidden="true" /> Now
        </span>
        <span className="legend__note">c/kWh {vat ? 'incl.' : 'excl.'} VAT · Finnish time</span>
      </figcaption>
      <details className="table-view">
        <summary>Show prices as a table</summary>
        <div className="table-view__scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Day</th>
                <th scope="col">Time</th>
                <th scope="col">c/kWh</th>
                <th scope="col">Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.start}>
                  <td>{r.dayLabel}</td>
                  <td>
                    {r.time}–{formatTime(r.end)}
                  </td>
                  <td className="num">{formatPrice(r.price)}</td>
                  <td>{[r.isCurrent && 'Now', r.inCheapest && 'Cheapest 3 h'].filter(Boolean).join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
