// Types matching the FastAPI response models (see /openapi.json on the backend).
// Decimal values arrive as strings (Pydantic serialises Decimal that way), so prices
// stay exact until we turn them into numbers for display.

export interface PricePoint {
  start: string // ISO datetime, Helsinki offset
  end: string
  resolution_minutes: number
  price_c_kwh: string
}

export interface PricesResponse {
  area: string
  start: string
  end: string
  timezone: string
  unit: 'c/kWh'
  vat_included: boolean
  vat_rate: string
  resolution_minutes: number
  count: number
  prices: PricePoint[]
}

export interface CheapestWindowResponse {
  date: string
  duration_minutes: number
  start: string
  end: string
  average_price_c_kwh: string
  unit: 'c/kWh'
  vat_included: boolean
  vat_rate: string
  data_complete: boolean
}

export type QualityStatus = 'pass' | 'info' | 'warn' | 'fail'
export type QualityColour = 'green' | 'yellow' | 'red' | 'unknown'

export interface QualityCheck {
  check_name: string
  day: string
  status: QualityStatus
  details: Record<string, unknown>
}

export interface QualitySummary {
  overall: QualityColour
  run_at: string | null
  checks: Record<string, QualityStatus>
  results: QualityCheck[]
}

/** Events streamed by POST /chat (Server-Sent Events). */
export type ChatEvent =
  | { type: 'session'; session_id: string }
  | { type: 'token'; text: string }
  | { type: 'tool'; name: string; ok: boolean }
  | { type: 'done'; answer: string; tools_used: string[]; unsupported_numbers: string[] }
  | { type: 'error'; message: string }
