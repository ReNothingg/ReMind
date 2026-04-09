import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.VITE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:5000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": "/src"
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['react', 'react-dom', 'react-router-dom'],
          'markdown': ['markdown-it', 'prismjs', 'dompurify', 'katex']
        }
      }
    },
    chunkSizeWarningLimit: 1000
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/chat': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/images': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/sessions': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/login': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/synthesize': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/translate': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
      '/canvas-action': {
        target: backendTarget,
        changeOrigin: true,
        secure: false,
      },
    }
  }
})
