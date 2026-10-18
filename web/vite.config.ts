import { defineConfig } from "vite";

export default defineConfig({
  envDir: "..", // read VITE_* from the repo-root .env
  server: { port: 5173 },
  build: {
    rollupOptions: {
      input: { phone: "phone.html" }, // resolved from web/
    },
  },
});
