import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, posix } from "node:path";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/** Depois do build, grava em dist/sw.js a lista de TODOS os arquivos do app e uma versão (hash do conteúdo).
 * O service worker guarda essa lista na instalação: sem isso, o primeiro acesso baixaria o JS/CSS/fontes antes de o
 * service worker existir e o app abriria em branco sem internet. A versão nova troca o cache antigo. */
function precacheManifest(): Plugin {
  let outDir = "dist";
  return {
    name: "ponto-precache-manifest",
    apply: "build",
    configResolved(c) {
      outDir = c.build.outDir;
    },
    closeBundle() {
      const files: string[] = [];
      const walk = (dir: string, rel: string) => {
        for (const name of readdirSync(join(dir))) {
          const full = join(dir, name);
          const url = posix.join(rel, name);
          if (statSync(full).isDirectory()) walk(full, url);
          else if (url.startsWith("assets/")) files.push("/" + url);
        }
      };
      walk(join(outDir, "assets"), "assets");
      files.sort();
      const hash = createHash("sha256");
      for (const f of files) hash.update(f);
      hash.update(readFileSync(join(outDir, "index.html")));
      const swPath = join(outDir, "sw.js");
      const sw = readFileSync(swPath, "utf-8")
        .replace('"__BUILD__"', JSON.stringify(hash.digest("hex").slice(0, 12)))
        .replace("[/* __ASSETS__ */]", JSON.stringify(files));
      writeFileSync(swPath, sw);
    },
  };
}

export default defineConfig({
  plugins: [react(), precacheManifest()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
