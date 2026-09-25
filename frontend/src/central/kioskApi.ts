/** Cliente da API da Central. Separado de `api.ts`: aqui não há usuário logado, só o token do APARELHO. */
const BASE = "/api";
const KEY = "ponto.kiosk.token";

export class KioskApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

export const getToken = (): string | null => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
export const setToken = (t: string | null) => {
  try {
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  } catch {
    /* sem armazenamento: o aparelho não consegue guardar o pareamento */
  }
};

async function call<T>(path: string, body?: unknown, token = getToken()): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(token ? { "X-Kiosk-Token": token } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new KioskApiError(0, "Central sem conexão com o servidor");
  }
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    const d = j.detail;
    const message = typeof d === "string" ? d : d?.message ?? (Array.isArray(d) ? "Dados inválidos" : `Erro ${res.status}`);
    throw new KioskApiError(res.status, message, typeof d === "object" && d ? d.code : undefined);
  }
  return res.json();
}

export interface KioskState {
  company: string;
  timezone: string;
  server_time: string;
  kiosk: { id: number; name: string; latitude: number | null; longitude: number | null; radius_m: number };
  pin_required: boolean;
  photo_required: boolean;
  consent_text: string;
  offline?: { enabled: boolean; max_hours: number };
}

export interface Identified {
  ticket: string;
  expires_in: number;
  first_name: string;
  needs_consent: boolean;
  next_kind: string;
  next_label: string;
  sequence: number;
  has_break: boolean;
}

export interface PunchResult {
  nsr: number;
  kind: string;
  label: string;
  time_local: string;
  hash_short: string;
  first_name: string;
}

export const pair = (code: string) => call<{ token: string; kiosk: { id: number; name: string } }>("/kiosk/pair", { pairing_code: code }, null);
export const getState = () => call<KioskState>("/kiosk/state");
export const identify = (method: "qr" | "code" | "cpf", value: string, pin?: string) =>
  call<Identified>("/kiosk/identify", { method, value, ...(pin ? { pin } : {}) });
export const consentPhoto = (ticket: string) => call<{ ok: boolean }>("/kiosk/consent-photo", { ticket });
export const punch = (ticket: string, photo: string, lat?: number, lon?: number) =>
  call<PunchResult>("/kiosk/punch", {
    ticket, photo, latitude: lat, longitude: lon, client_key: crypto.randomUUID(),
  });

export const offlinePunch = (i: { key: string; qr: string; photo: string; occurred_at: string; device_time: string; skew_ms: number; latitude?: number; longitude?: number }) =>
  call<{ nsr: number; kind: string; label: string }>("/kiosk/offline-punch", {
    qr: i.qr, photo: i.photo, client_key: i.key, occurred_at: i.occurred_at, device_time: i.device_time, skew_ms: i.skew_ms,
    latitude: i.latitude, longitude: i.longitude,
  });
