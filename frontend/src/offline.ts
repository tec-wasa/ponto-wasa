/** Fila de marcações off-line: guardada no aparelho até o envio. Sem dependências do navegador (o armazenamento é injetado). */

export interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface QueuedPunch {
  key: string; // idempotência: reenviar nunca duplica a marcação
  kind: string;
  occurred_at: string; // ISO UTC: hora do aparelho corrigida pelo desvio
  device_time: string; // hora crua do relógio do aparelho
  skew_ms: number;
  collector: string;
  device_id: string;
  latitude?: number;
  longitude?: number;
  accuracy_m?: number;
  queued_at: string;
  photo?: string; // JPEG em base64, opcional: enviado depois da batida, nunca a bloqueia
  status: "pending" | "rejected";
  error?: string;
}

/** Última medida do relógio do servidor: é o que torna a hora off-line confiável. */
export interface SkewRecord {
  ms: number; // servidor - aparelho
  at: number; // Date.now() do aparelho na medição
  enabled: boolean;
  maxHours: number;
}

export const MAX_SKEW_AGE_MS = 7 * 24 * 3600 * 1000;

const queueKey = (uid: number) => `ponto.queue.${uid}`;
const SKEW_KEY = "ponto.skew";

export function loadQueue(store: Store, uid: number): QueuedPunch[] {
  try {
    const v = JSON.parse(store.getItem(queueKey(uid)) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function saveQueue(store: Store, uid: number, q: QueuedPunch[]): void {
  store.setItem(queueKey(uid), JSON.stringify(q)); // se falhar, quem chamou precisa saber: não engolimos o erro
}

export function enqueue(store: Store, uid: number, item: QueuedPunch): void {
  const q = loadQueue(store, uid);
  if (q.some((x) => x.key === item.key)) return;
  saveQueue(store, uid, [...q, item]);
}

export function update(store: Store, uid: number, key: string, patch: Partial<QueuedPunch>): void {
  saveQueue(store, uid, loadQueue(store, uid).map((x) => (x.key === key ? { ...x, ...patch } : x)));
}

export function remove(store: Store, uid: number, key: string): void {
  saveQueue(store, uid, loadQueue(store, uid).filter((x) => x.key !== key));
}

export function loadSkew(store: Store): SkewRecord | null {
  try {
    const v = JSON.parse(store.getItem(SKEW_KEY) ?? "null");
    return v && typeof v.ms === "number" && typeof v.at === "number" ? v : null;
  } catch {
    return null;
  }
}

export function saveSkew(store: Store, rec: SkewRecord): void {
  try {
    store.setItem(SKEW_KEY, JSON.stringify(rec));
  } catch {
    /* sem armazenamento: o modo off-line simplesmente não fica disponível */
  }
}

export type OfflineCheck = { ok: true; occurredAt: Date; skewMs: number } | { ok: false; reason: string };

/** Pode marcar sem rede? A hora do aparelho só vale se o relógio foi medido há pouco e não foi mexido depois. */
export function canPunchOffline(rec: SkewRecord | null, deviceNow: number): OfflineCheck {
  if (!rec) return { ok: false, reason: "Conecte-se pelo menos uma vez neste aparelho antes de usar o modo sem internet." };
  if (!rec.enabled) return { ok: false, reason: "O registro sem internet está desativado para esta empresa." };
  if (deviceNow < rec.at) {
    return { ok: false, reason: "O relógio do aparelho voltou no tempo. Conecte-se à internet para registrar." };
  }
  if (deviceNow - rec.at > MAX_SKEW_AGE_MS) {
    return { ok: false, reason: "Faz mais de 7 dias que este aparelho não se conecta. Conecte-se para registrar." };
  }
  return { ok: true, occurredAt: new Date(deviceNow + rec.ms), skewMs: rec.ms };
}

/** Falhas que o tempo resolve (rede, servidor, sessão): a marcação continua na fila. As demais são recusas definitivas. */
export function isTransient(status: number): boolean {
  return status === 0 || status === 401 || status === 408 || status === 429 || status >= 500;
}

export interface SyncResult {
  sent: number;
  rejected: number;
  stopped: boolean; // parou numa falha transitória: tentará de novo
}

/** Envia as pendentes em ordem. `send` lança um erro com `status` quando o servidor recusa. */
export async function syncQueue(
  store: Store, uid: number, send: (item: QueuedPunch) => Promise<void>,
): Promise<SyncResult> {
  const result: SyncResult = { sent: 0, rejected: 0, stopped: false };
  for (const item of loadQueue(store, uid).filter((x) => x.status === "pending")) {
    try {
      await send(item);
      remove(store, uid, item.key);
      result.sent++;
    } catch (e) {
      const status = typeof (e as { status?: unknown }).status === "number" ? (e as { status: number }).status : 0;
      if (isTransient(status)) {
        result.stopped = true;
        break; // mantém a ordem: não adianta pular para as seguintes
      }
      update(store, uid, item.key, { status: "rejected", error: e instanceof Error ? e.message : "Recusada pelo servidor" });
      result.rejected++;
    }
  }
  return result;
}

/** Prazo restante (em horas) para enviar uma marcação, dado o limite do servidor. */
export function hoursLeft(item: QueuedPunch, maxHours: number, now: number): number {
  return maxHours - (now - new Date(item.occurred_at).getTime()) / 3_600_000;
}
