import { describe, expect, it } from "vitest";
import { MAX_ITEMS, enqueue, isFinalRejection, loadQueue, remove, type QueueItem } from "./offlineQueue";

const mem = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};
const item = (key: string, photo = "abc"): QueueItem => ({ key, qr: "PB1.1.2.1.aaaaaaaaaaaaaaaaaaaa", photo, occurred_at: "2026-01-01T10:00:00Z", device_time: "2026-01-01T10:00:01Z", skew_ms: -1000 });

describe("fila offline da Central", () => {
  it("guarda em ordem e remove pelo key", () => {
    const s = mem();
    expect(enqueue(item("a"), s) && enqueue(item("b"), s)).toBe(true);
    expect(loadQueue(s).map((i) => i.key)).toEqual(["a", "b"]);
    remove("a", s);
    expect(loadQueue(s).map((i) => i.key)).toEqual(["b"]);
  });
  it("recusa quando a fila enche (não perde em silêncio)", () => {
    const s = mem();
    for (let i = 0; i < MAX_ITEMS; i++) expect(enqueue(item(`k${i}`), s)).toBe(true);
    expect(enqueue(item("extra"), s)).toBe(false);
  });
  it("recusa por tamanho e quando o armazenamento falha", () => {
    expect(enqueue(item("big", "x".repeat(3_600_000)), mem())).toBe(false);
    const broken = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
    expect(enqueue(item("a"), broken)).toBe(false);
  });
  it("classifica recusa definitiva x falha passageira", () => {
    expect([422, 409, 403, 413].every(isFinalRejection)).toBe(true);
    expect([0, 429, 500, 502, 503, 401].some(isFinalRejection)).toBe(false);
  });
});
