import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// VITE_BASE is injected by the GitHub Pages workflow as /pdf_to_md_app/.
// Falls back to /pdf_to_md_app/ for both local and CI to keep assets working.
export default defineConfig({
  base: process.env.VITE_BASE ?? '/pdf_to_md_app/',
  plugins: [react()],
})
