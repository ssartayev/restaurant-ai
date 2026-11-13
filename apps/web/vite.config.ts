import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; the proxy keeps cookies same-origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://localhost:8000", "/healthz": "http://localhost:8000" } },
});
