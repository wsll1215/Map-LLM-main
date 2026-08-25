import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/frontend/",
  server: {
    port: 5200,
    proxy: {
      "/mapping": "http://127.0.0.1:8001",
      "/accounts": "http://127.0.0.1:8001",
      "/generated_maps": "http://127.0.0.1:8001"
    },
  },
  build: {
    outDir: "../static/frontend",
    emptyOutDir: true,
    manifest: false,
    rollupOptions: { output: { entryFileNames: "assets/app.js", chunkFileNames: "assets/[name].js", assetFileNames: (assetInfo) => assetInfo.name?.endsWith(".css") ? "assets/app.css" : "assets/[name][extname]" } },
  },
});
