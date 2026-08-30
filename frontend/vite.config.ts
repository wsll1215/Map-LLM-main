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
    rollupOptions: { output: { entryFileNames: "assets/app-v3.js", chunkFileNames: "assets/[name]-[hash].js", manualChunks: { "antd-vendor": ["antd", "@ant-design/icons"], "react-runtime": ["react/jsx-runtime", "react/jsx-dev-runtime"], "map-shared": ["./src/map/mapDataLoader.ts", "./src/map/layerRegistry.ts", "./src/map/styles.ts", "./src/map/renderPolicy.ts"] }, assetFileNames: (assetInfo) => assetInfo.name?.endsWith(".css") ? "assets/app-v3.css" : "assets/[name][extname]" } },
  },
});
