import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  server: {
    port: Number(process.env.MINDCHIME_WEB_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.MINDCHIME_API_PORT || 8765}`,
        changeOrigin: true,
      },
    },
  },
  build: { chunkSizeWarningLimit: 1200 },
})
