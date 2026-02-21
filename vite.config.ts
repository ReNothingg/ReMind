import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": "/src"
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'cytoscape': ['cytoscape-fcose'],
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
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/chat': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/sessions': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/login': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/synthesize': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/translate': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
      '/canvas-action': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
    }
  }
})
