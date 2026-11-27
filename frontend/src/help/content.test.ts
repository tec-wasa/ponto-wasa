import { describe, expect, it } from "vitest";
import { GROUPS, TOPICS } from "./content";

const ROUTES = ["/", "/registros", "/solicitacoes", "/banco", "/conta", "/mais", "/gestao", "/gestao/aprovacoes", "/gestao/espelhos",
  "/gestao/tratamento", "/gestao/inconsistencias", "/gestao/banco", "/gestao/ausencias", "/gestao/relatorios", "/gestao/cadastros", "/gestao/empresa"];

describe("manual", () => {
  it("tópicos com id único, grupo válido e conteúdo", () => {
    const ids = TOPICS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of TOPICS) {
      expect(GROUPS).toContain(t.group);
      expect(t.blocks.length).toBeGreaterThan(0);
      expect(t.summary.length).toBeGreaterThan(10);
    }
    for (const g of GROUPS) expect(TOPICS.some((t) => t.group === g)).toBe(true);
  });

  it("os atalhos apontam para telas que existem", () => {
    for (const t of TOPICS) if (t.where) expect(ROUTES).toContain(t.where.path);
  });

  it("negritos fechados", () => {
    for (const t of TOPICS) {
      for (const b of t.blocks) {
        for (const s of [b.text, b.tip, b.warn, b.h, ...(b.steps ?? []), ...(b.list ?? [])]) {
          if (s) expect((s.match(/\*\*/g) ?? []).length % 2, `${t.id}: ${s}`).toBe(0);
        }
      }
    }
  });
});
