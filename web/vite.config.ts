import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  envDir: "..", // read VITE_* from the repo-root .env
  server: { port: 5173 },
  build: {
    rollupOptions: {
      input: { phone: resolve(__dirname, "phone.html") },
    },
  },
});
