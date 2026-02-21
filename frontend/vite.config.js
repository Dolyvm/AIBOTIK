import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': 'http://backend:8080'  // Проксируем API запросы
    },
    watch: {
      usePolling: true,           // Включаем polling для Docker
      interval: 1000               // Проверка каждую секунду
    },
    hmr: {
      overlay: true                // Показывать ошибки на экране
    }
  }
})