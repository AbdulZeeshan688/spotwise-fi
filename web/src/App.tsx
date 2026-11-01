import { useEffect, useMemo, useState } from 'react'
import { getCheapestWindow, getPrices, getQuality } from './api/client'
import type { CheapestWindowResponse, PricesResponse, QualitySummary } from './api/types'
import { ChatPanel } from './components/ChatPanel'
import { PriceChart } from './components/PriceChart'
import { QualityBadge } from './components/QualityBadge'
import { toChartRows } from './lib/chartData'
import { addDays, formatDay, formatPrice, formatTime, helsinkiDate } from './lib/time'

/** The current time, refreshed every minute so the "now" bar moves. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])
  return now
}

/** True once `active` has been true for `ms` (e.g. "loading is taking long"). */
function useTakingLong(active: boolean, ms = 4000): boolean {
  const [long, setLong] = useState(false)
  useEffect(() => {
    if (!active) return
    const id = setTimeout(() => setLong(true), ms)
    return () => {
      clearTimeout(id)
      setLong(false)
    }
  }, [active, ms])
  return active && long
}

export default function App() {
  const now = useNow()
  const today = helsinkiDate(now)
  const tomorrow = addDays(today, 1)
  const [resolution, setResolution] = useState<15 | 60>(15)
  const [vat, setVat] = useState(true)
  const [prices, setPrices] = useState<PricesResponse | null>(null)
  const [windows, setWindows] = useState<CheapestWindowResponse[]>([])
  const [error, setError] = useState<string | null>(null)
  const [quality, setQuality] = useState<QualitySummary | null>(null)
  const [qualityError, setQualityError] = useState<string | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    Promise.all([
      getPrices({ from: today, to: addDays(today, 2), resolution, vat }, ctrl.signal),
      getCheapestWindow(today, 3, vat, ctrl.signal),
      getCheapestWindow(tomorrow, 3, vat, ctrl.signal),
    ])
      .then(([p, w1, w2]) => {
        setError(null)
        setPrices(p)
        setWindows([w1, w2].filter((w): w is CheapestWindowResponse => w !== null))
      })
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) setError(err instanceof Error ? err.message : String(err))
      })
    return () => ctrl.abort()
  }, [today, tomorrow, resolution, vat])

  useEffect(() => {
    const ctrl = new AbortController()
    getQuality(ctrl.signal)
      .then(setQuality)
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) setQualityError(err instanceof Error ? err.message : String(err))
      })
    return () => ctrl.abort()
  }, [today])

  const rows = useMemo(
    () => (prices ? toChartRows(prices.prices, now, windows) : []),
    [prices, now, windows],
  )
  const current = rows.find((r) => r.isCurrent)
  // The free API host sleeps when idle; the first request can take up to a minute
  const waking = useTakingLong(!prices && !error)
  const tomorrowPublished = rows.filter((r) => r.day === tomorrow).length > 4

  return (
    <div className="app">
      <header className="header">
        <h1>
          SpotWise <span className="header__fi">FI</span>
        </h1>
        <QualityBadge summary={quality} error={qualityError} />
      </header>

      <main className="layout">
        <section className="prices" aria-labelledby="prices-title">
          <div className="prices__head">
            <h2 id="prices-title">Today and tomorrow</h2>
            <div className="toggles">
              <div className="segmented" role="group" aria-label="Resolution">
                <button type="button" aria-pressed={resolution === 15} onClick={() => setResolution(15)}>
                  15 min
                </button>
                <button type="button" aria-pressed={resolution === 60} onClick={() => setResolution(60)}>
                  Hourly
                </button>
              </div>
              <div className="segmented" role="group" aria-label="VAT">
                <button type="button" aria-pressed={vat} onClick={() => setVat(true)}>
                  Incl. VAT
                </button>
                <button type="button" aria-pressed={!vat} onClick={() => setVat(false)}>
                  Excl. VAT
                </button>
              </div>
            </div>
          </div>

          <dl className="facts">
            <div className="fact">
              <dt>Now{current ? ` (${current.time})` : ''}</dt>
              <dd>{current ? `${formatPrice(current.price)} c/kWh` : '–'}</dd>
            </div>
            {windows.map((w) => (
              <div className="fact" key={w.date}>
                <dt>Cheapest 3 h · {formatDay(w.start)}</dt>
                <dd>
                  {formatTime(w.start)}–{formatTime(w.end)} · {formatPrice(w.average_price_c_kwh)} c/kWh
                </dd>
              </div>
            ))}
          </dl>

          {error && (
            <p className="notice notice--error" role="alert">
              Couldn't load prices: {error}
            </p>
          )}
          {!error && !prices && (
            <p className="notice" role="status">
              {waking
                ? 'Waking up the free server… this can take up to a minute the first time.'
                : 'Loading prices…'}
            </p>
          )}
          {prices && rows.length === 0 && <p className="notice">No prices stored for today yet.</p>}
          {rows.length > 0 && <PriceChart rows={rows} vat={vat} />}
          {prices && !tomorrowPublished && (
            <p className="notice">Tomorrow's prices are published around 14:00 Finnish time.</p>
          )}
        </section>

        <ChatPanel />
      </main>

      <footer className="footer">
        Day-ahead spot prices for Finland (ENTSO-E / porssisahko.net). Prices shown in c/kWh,{' '}
        {vat ? 'including' : 'excluding'} 25.5% VAT, without transfer fees. Times are Finnish time.
      </footer>
    </div>
  )
}
