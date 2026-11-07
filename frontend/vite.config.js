// While developing, Vite serves the page and passes /api on to the planner (python -m homecare.web).
// Built (npm run build), the page goes to dist/, and the planner serves it itself.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/map-data": "http://127.0.0.1:8000" },
  },
});
