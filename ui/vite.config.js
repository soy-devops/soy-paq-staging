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
        assetFileNames: 'soypaq-wms.[ext]',
      },
    },
  },
})
