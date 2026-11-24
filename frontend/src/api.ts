const BASE = "/api";
const KEY = "ponto.tokens";

interface Tokens {
  access: string;
  refresh: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public data?: unknown) {
    super(message);
  }
}

export function getTokens(): Tokens | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
}

export function setTokens(t: Tokens | null) {
  try {
    if (t) localStorage.setItem(KEY, JSON.stringify(t));
    else localStorage.removeItem(KEY);
  } catch {
    /* armazenamento indisponível: sessão só em memória não é suportada */
  }
}

async function send(path: string, method: string, body: unknown, token?: string): Promise<Response> {
  try {
    return await fetch(BASE + path, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Sem conexão com o servidor");
  }
}

async function tryRefresh(): Promise<boolean> {
  const t = getTokens();
  if (!t) return false;
  const res = await send("/auth/refresh", "POST", { refresh_token: t.refresh }).catch(() => null);
  if (!res?.ok) return false;
  const j = await res.json();
  setTokens({ access: j.access_token, refresh: j.refresh_token });
  return true;
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? "valor inválido").join("; ");
  return `Erro ${status}`;
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method ?? "GET";
  let res = await send(path, method, opts.body, getTokens()?.access);
  if (res.status === 401 && path !== "/auth/login" && (await tryRefresh())) {
    res = await send(path, method, opts.body, getTokens()?.access);
  }
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/auth/login") setTokens(null);
    const code = j.detail && typeof j.detail === "object" && "code" in j.detail ? String(j.detail.code) : undefined;
    if (res.status === 403 && (code === "password_change_required" || code === "two_factor_required")) {
      window.dispatchEvent(new Event("ponto:restricted")); // a conta tem uma pendência de segurança: o app reabre a tela certa
    }
    throw new ApiError(res.status, errorMessage(j.detail, res.status), code, j);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Busca um arquivo protegido (imagem) e devolve uma URL temporária para exibi-lo. Quem chama deve liberar com URL.revokeObjectURL. */
export async function blobUrl(path: string): Promise<string> {
  let res = await send(path, "GET", undefined, getTokens()?.access);
  if (res.status === 401 && (await tryRefresh())) res = await send(path, "GET", undefined, getTokens()?.access);
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new ApiError(res.status, errorMessage(j.detail, res.status));
  }
  return URL.createObjectURL(await res.blob());
}

export const clearApiCache = () => {
  navigator.serviceWorker?.controller?.postMessage("clear-api");
};

/** Baixa um arquivo protegido (envia o token) e o salva com o nome sugerido pelo servidor. */
export async function download(path: string, fallbackName: string): Promise<void> {
  let res = await send(path, "GET", undefined, getTokens()?.access);
  if (res.status === 401 && (await tryRefresh())) res = await send(path, "GET", undefined, getTokens()?.access);
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new ApiError(res.status, errorMessage(j.detail, res.status));
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
