import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Tauri 期望固定端口用于 devUrl
  server: {
    port: 8173,
    strictPort: true,
    host: '127.0.0.1',
  },
  // Tauri 在生产模式使用相对路径
  base: './',
  build: {
    outDir: 'dist',
    target: ['es2021', 'chrome105', 'safari15'],
    minify: !process.env.TAURI_DEBUG ? 'esbuild' : false,
    sourcemap: !!process.env.TAURI_DEBUG,
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1000,
  },
  esbuild: {
    drop: process.env.TAURI_DEBUG ? [] : ['console', 'debugger'],
  },
  clearScreen: false,
  envPrefix: ['VITE_', 'TAURI_'],
})
