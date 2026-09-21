import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

// The whole app ships under /assets/fieldmate/pwa/ and nothing lives in www/.
//
// Two constraints force this, and they pull in the same direction:
//
// 1. Service worker scope. A worker only controls pages inside its own path, and Frappe sends
//    no Service-Worker-Allowed header, so the worker must sit beside the app. Serving the app
//    from /fieldmate while the worker sat in /assets/ meant the worker never controlled
//    anything and offline was impossible.
// 2. Frappe renders www/ files as Jinja templates - "js" and "css" are in
//    UNSUPPORTED_STATIC_PAGE_TYPES, so they never take the raw static path. A 198 KB minified
//    bundle contains sequences Jinja treats as markup, which returned HTTP 417. Only /assets/
//    is served as true static.
//
// Routing is hash-based, so every deep link is still a request for index.html itself and no
// server-side rewrite is needed. /fieldmate stays as a small redirect for people typing it.
const BASE = '/assets/fieldmate/pwa/'

export default defineConfig({
  base: BASE,
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      manifest: {
        name: 'FieldMate',
        short_name: 'FieldMate',
        description: 'Field sales for distribution teams',
        theme_color: '#004ac6',
        background_color: '#faf8ff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: BASE,
        scope: BASE,
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,webmanifest}'],
        navigateFallback: BASE + 'index.html',
        navigateFallbackAllowlist: [/^\/assets\/fieldmate\/pwa\//],
        // API responses are never cached. A stale order is worse than no order.
        runtimeCaching: [{ urlPattern: /\/api\/method\//, handler: 'NetworkOnly' }],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  build: {
    outDir: '../fieldmate/public/pwa',
    emptyOutDir: true,
    target: 'es2018',
    sourcemap: false,
  },
})
