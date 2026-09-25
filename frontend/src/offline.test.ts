import { describe, expect, it } from "vitest";
import {
  type QueuedPunch, type Store, canPunchOffline, enqueue, hoursLeft, isTransient, loadQueue, syncQueue,
} from "./offline";

function memory(): Store {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
}

const item = (key: string, kind = "entrada"): QueuedPunch => ({
  key, kind, occurred_at: "2026-01-01T10:00:00.000Z", device_time: "2026-01-01T10:00:00.000Z", skew_ms: 0,
  collector: "01", device_id: "d", queued_at: "2026-01-01T10:00:00.000Z", status: "pending",
});
const fail = (status: number, message = "erro") => Object.assign(new Error(message), { status });

describe("canPunchOffline", () => {
  const rec = { ms: 5000, at: 1_000_000, enabled: true, maxHours: 72 };
  it("corrige a hora do aparelho pelo desvio medido", () => {
    const r = canPunchOffline(rec, 1_060_000);
    expect(r.ok && r.occurredAt.getTime()).toBe(1_065_000);
  });
  it("recusa sem medição, desativado, relógio voltando e medição velha", () => {
    expect(canPunchOffline(null, 1).ok).toBe(false);
    expect(canPunchOffline({ ...rec, enabled: false }, 1_060_000).ok).toBe(false);
    expect(canPunchOffline(rec, 999_999).ok).toBe(false);
    expect(canPunchOffline(rec, 1_000_000 + 8 * 86_400_000).ok).toBe(false);
  });
});

describe("fila", () => {
  it("não duplica a mesma chave e é separada por usuário", () => {
    const s = memory();
    enqueue(s, 1, item("a"));
    enqueue(s, 1, item("a"));
    enqueue(s, 2, item("b"));
    expect(loadQueue(s, 1)).toHaveLength(1);
    expect(loadQueue(s, 2)[0].key).toBe("b");
  });
  it("armazenamento corrompido vira fila vazia", () => {
    const s = memory();
    s.setItem("ponto.queue.1", "{lixo");
    expect(loadQueue(s, 1)).toEqual([]);
  });
});

describe("syncQueue", () => {
  it("envia em ordem e esvazia a fila", async () => {
    const s = memory();
    enqueue(s, 1, item("a"));
    enqueue(s, 1, item("b", "saida"));
    const sent: string[] = [];
    const r = await syncQueue(s, 1, async (i) => void sent.push(i.key));
    expect(sent).toEqual(["a", "b"]);
    expect(r).toEqual({ sent: 2, rejected: 0, stopped: false });
    expect(loadQueue(s, 1)).toEqual([]);
  });
  it("falha de rede para e mantém tudo, na ordem", async () => {
    const s = memory();
    enqueue(s, 1, item("a"));
    enqueue(s, 1, item("b"));
    const r = await syncQueue(s, 1, async () => { throw fail(0); });
    expect(r.stopped).toBe(true);
    expect(loadQueue(s, 1).map((x) => x.key)).toEqual(["a", "b"]);
  });
  it("recusa definitiva marca como rejeitada e segue para a próxima", async () => {
    const s = memory();
    enqueue(s, 1, item("a"));
    enqueue(s, 1, item("b"));
    const r = await syncQueue(s, 1, async (i) => { if (i.key === "a") throw fail(409, "Sequência inválida"); });
    expect(r).toEqual({ sent: 1, rejected: 1, stopped: false });
    const q = loadQueue(s, 1);
    expect(q).toHaveLength(1);
    expect(q[0]).toMatchObject({ key: "a", status: "rejected", error: "Sequência inválida" });
    const again = await syncQueue(s, 1, async () => { throw fail(500); }); // rejeitada não é reenviada
    expect(again.stopped).toBe(false);
  });
});

describe("regras", () => {
  it("classifica falhas transitórias", () => {
    for (const st of [0, 401, 408, 429, 500, 503]) expect(isTransient(st)).toBe(true);
    for (const st of [403, 404, 409, 422]) expect(isTransient(st)).toBe(false);
  });
  it("calcula o prazo restante", () => {
    const now = new Date("2026-01-01T22:00:00Z").getTime();
    expect(hoursLeft(item("a"), 72, now)).toBe(60);
  });
});
