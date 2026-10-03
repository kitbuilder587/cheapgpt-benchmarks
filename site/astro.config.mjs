import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://kitbuilder587.github.io",
  base: "/cheapgpt-benchmarks",
  output: "static",
  vite: { server: { fs: { allow: [".."] } } },
});

