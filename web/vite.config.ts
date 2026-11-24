import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development the React app runs on :5173 and proxies /api to the FastAPI server on :8720.
// For the demo, `npm run build` writes web/dist, which FastAPI serves itself (one process).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8720" } },
});
