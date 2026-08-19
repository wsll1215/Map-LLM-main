import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/frontend/",
  server: {
    port: 5173,
    proxy: {
      "/mapping": "http://127.0.0.1:8000",
      "/accounts": "http://127.0.0.1:8000",
      "/generated_maps": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000"
    },
  },
  build: {
    outDir: "../static/frontend",
    emptyOutDir: true,
    manifest: false,
    rollupOptions: { output: { entryFileNames: "assets/app.js", chunkFileNames: "assets/[name].js", assetFileNames: "assets/[name][extname]" } },
  },
});
