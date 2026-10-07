import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * The phone's own test run.
 *
 * Until this existed, 955 tests covered the server and **none of them touched the PWA**. Three
 * bugs reached a rep that way in one week, each of them a figure the server had answered
 * correctly and the phone drew wrong:
 *
 *   - the GST on an order the phone had booked was never shown, so a rep read out a number short
 *     by the whole of the tax;
 *   - a kirana's screen showed its distributor's credit limit under a heading that said it was
 *     the shop's;
 *   - a check-in into the next shop silently closed the visit the rep was standing in.
 *
 * Every one of them is cheap to catch here and was impossible to catch in Python. That is what
 * this directory is for.
 *
 * Separate from `vite.config.js` on purpose: that one builds a service worker and a manifest,
 * neither of which has anything to say in a test run.
 */
export default defineConfig({
  plugins: [vue()],
  test: {
    // Lighter than jsdom and enough for everything here: these are components and stores, not
    // layout. Nothing in this suite measures a pixel.
    environment: 'happy-dom',
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.js'],
    // A mock left on by one test is a failure attributed to the next one.
    restoreMocks: true,
    clearMocks: true,
  },
})
