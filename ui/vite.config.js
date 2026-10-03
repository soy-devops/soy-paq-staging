import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

export default defineConfig({
  base: '/assets/soypaq/wms/',
  plugins: [
    frappeui({ frappeProxy: false, jinjaBootData: false, buildConfig: false }),
    vue(),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  optimizeDeps: {
    exclude: ['frappe-ui'],
    include: ['tippy.js', 'engine.io-client', 'socket.io-client', 'debug'],
  },
  build: {
    outDir: fileURLToPath(new URL('../soypaq/public/wms', import.meta.url)),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: 'soypaq-wms.js',
        // Fonts keep their own names: with one fixed name for every asset, the two fonts
        // came out as soypaq-wms/soypaq-wms2 in a different order on each build.
        assetFileNames: (info) =>
          /\.woff2?$/.test(info.names?.[0] ?? info.name ?? '') ? 'fonts/[name][extname]' : 'soypaq-wms.[ext]',
      },
    },
  },
})
