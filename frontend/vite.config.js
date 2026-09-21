import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

// Built assets are served by Frappe from apps/fieldmate/fieldmate/public/pwa
// and reachable at /assets/fieldmate/pwa/. The HTML entry is copied into www/
// by the build script so website_route_rules can mount the SPA at /fieldmate.
export default defineConfig({
  base: '/assets/fieldmate/pwa/',
  plugins: [
    vue(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: 'auto',
      manifest: {
        name: 'FieldMate',
        short_name: 'FieldMate',
        description: 'Field sales for distribution teams',
        theme_color: '#004ac6',
        background_color: '#faf8ff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/fieldmate',
        scope: '/fieldmate',
      },
      workbox: {
        // App shell is precached. API calls are never cached - stale orders are worse
        // than no orders. Offline reads come from IndexedDB, not from the HTTP cache.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        navigateFallback: null,
        runtimeCaching: [
          {
            urlPattern: /\/api\/method\/fieldmate\./,
            handler: 'NetworkOnly',
          },
        ],
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
