import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// `base` defaults to '/' for local dev. For a GitHub Pages *project* site the
// app is served from /<repo>/, so the Pages workflow sets VITE_BASE=/pdf_to_md_app/.
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? '/',
})
