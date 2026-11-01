# SpotWise FI — web app

Vite + React + TypeScript (strict) front end: price chart for today and tomorrow, and a
chat panel that streams answers from the SpotWise agent.

```bash
cp .env.example .env      # VITE_API_URL=http://localhost:8000
npm install
npm run dev               # http://localhost:5173 (start the API first)
npm test                  # Vitest + Testing Library
npm run build             # type check + production build in dist/
```

- `src/api/`: typed client for the FastAPI backend (types match the Pydantic models) and the SSE chat stream.
- `src/lib/`: Helsinki-time formatting and the chart-data transform (pure, unit-tested).
- `src/components/`: `PriceChart` (Recharts), `ChatPanel`, `QualityBadge`.

No API keys live in the front end; it only talks to the SpotWise API.
