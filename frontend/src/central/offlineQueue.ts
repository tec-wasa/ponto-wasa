/** Fila local da Central sem internet (opção C): guarda só o QR do crachá impresso, a foto e a hora. Nada de dados de pessoas. */
const KEY = "ponto.kiosk.offlineQueue";
export const MAX_ITEMS = 40;
export const MAX_BYTES = 3_500_000; // localStorage costuma ter ~5 MB; a foto (base64) é o que pesa

export interface QueueItem {
  key: string; // idempotência: o servidor ignora o reenvio
  qr: string;
  photo: string;
  occurred_at: string; // hora do aparelho corrigida pelo desvio medido pela última vez com o servidor
  device_time: string;
  skew_ms: number;
  latitude?: number;
  longitude?: number;
}

type Store = Pick<Storage, "getItem" | "setItem">;

export function loadQueue(store: Store = localStorage): QueueItem[] {
  try {
    const v = JSON.parse(store.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function save(items: QueueItem[], store: Store): boolean {
  try {
    store.setItem(KEY, JSON.stringify(items));
    return true;
  } catch {
    return false; // sem espaço: quem chamou avisa a pessoa em vez de perder a batida em silêncio
  }
}

/** false = fila cheia ou sem espaço: a batida NÃO foi guardada e a pessoa precisa ser avisada. */
export function enqueue(item: QueueItem, store: Store = localStorage): boolean {
  const items = loadQueue(store);
  const bytes = items.reduce((n, i) => n + i.photo.length, 0) + item.photo.length;
  if (items.length >= MAX_ITEMS || bytes > MAX_BYTES) return false;
  return save([...items, item], store);
}

export function remove(key: string, store: Store = localStorage): void {
  save(loadQueue(store).filter((i) => i.key !== key), store);
}

/** Motivo de o servidor ter recusado de vez (vale descartar) versus falha passageira (manter e tentar de novo). */
export function isFinalRejection(status: number): boolean {
  return status === 422 || status === 413 || status === 409 || status === 403;
}
