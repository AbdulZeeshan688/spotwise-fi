import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Run tests in another timezone to prove the UI always shows Helsinki time
    env: { TZ: 'America/New_York' },
  },
})
