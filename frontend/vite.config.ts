import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Lokale Entwicklung: /api und der WebSocket gehen an den laufenden
// Docker-Stack (HAProxy auf 8443 mit lokalem Zertifikat). Der Host-Header
// bleibt localhost:5173, damit die Origin-Prüfung im Backend passt.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "https://localhost:8443",
        secure: false,
        ws: true,
      },
    },
  },
});
