import { api } from "./api";
import { type QueuedPunch, type SyncResult, syncQueue } from "./offline";

let running = false;

export const QUEUE_EVENT = "ponto:queue";
export const notifyQueue = () => window.dispatchEvent(new Event(QUEUE_EVENT));

export async function sendPunch(item: QueuedPunch): Promise<void> {
  const punch = await api<{ id: number }>("/punches", {
    method: "POST",
    body: {
      kind: item.kind, offline: true, occurred_at: item.occurred_at, device_time: item.device_time, skew_ms: item.skew_ms,
      client_key: item.key, device_id: item.device_id, collector: item.collector,
      latitude: item.latitude, longitude: item.longitude, accuracy_m: item.accuracy_m,
    },
  });
  if (item.photo) {
    // A foto é opcional: se falhar, a batida já está registrada e segue valendo.
    await api(`/punches/${punch.id}/photo`, { method: "POST", body: { image_base64: item.photo } }).catch(() => undefined);
  }
}

/** Envia a fila do usuário. Uma execução por vez; devolve null se já havia uma em andamento ou sem rede. */
export async function runSync(uid: number): Promise<SyncResult | null> {
  if (running || !navigator.onLine) return null;
  running = true;
  try {
    const r = await syncQueue(localStorage, uid, sendPunch);
    notifyQueue();
    return r;
  } finally {
    running = false;
  }
}
