export const KIND_LABEL: Record<string, string> = {
  entrada: "Entrada",
  saida: "Saída",
  inicio_intervalo: "Intervalo",
  fim_intervalo: "Retorno do intervalo",
};

export const IN_KINDS = ["entrada", "fim_intervalo"];

export const ROLE_LABEL: Record<string, string> = {
  employee: "Colaborador",
  manager: "Gestor",
  hr: "RH",
  admin: "Administrador",
  auditor: "Auditor",
};

/** 485 -> "8h05"; -30 -> "-0h30" */
export function fmtMinutes(m: number): string {
  const sign = m < 0 ? "-" : "";
  const a = Math.abs(m);
  return `${sign}${Math.floor(a / 60)}h${String(a % 60).padStart(2, "0")}`;
}

/** Datas da API vêm em UTC sem sufixo; interpreta como UTC. */
export function parseUtc(iso: string): Date {
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function fmtDateTime(iso: string, tz: string): string {
  return parseUtc(iso).toLocaleString("pt-BR", { timeZone: tz, dateStyle: "short", timeStyle: "medium" });
}

/** Data e hora sem segundos: para pedidos e listas, onde os segundos só atrapalham. */
export function fmtDateTimeMin(iso: string, tz: string): string {
  return parseUtc(iso).toLocaleString("pt-BR", { timeZone: tz, dateStyle: "short", timeStyle: "short" });
}

export function fmtTime(iso: string, tz: string): string {
  return parseUtc(iso).toLocaleTimeString("pt-BR", { timeZone: tz, hour: "2-digit", minute: "2-digit" });
}

/** Diferença (local - UTC) em ms do fuso `tz` no instante `date`. */
function tzOffsetMs(date: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(date);
  const g = (t: string) => Number(parts.find((p) => p.type === t)!.value);
  const asUtc = Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute"), g("second"));
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** Converte data/hora locais do fuso `tz` (AAAA-MM-DD, HH:MM) para ISO UTC. */
export function localToUtcIso(date: string, time: string, tz: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  const first = guess - tzOffsetMs(new Date(guess), tz);
  return new Date(guess - tzOffsetMs(new Date(first), tz)).toISOString();
}

export function currentMonth(tz: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit" }).format(new Date());
  return parts.slice(0, 7);
}

export function todayLocal(tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function fmtMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const text = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" });
  return text.charAt(0).toUpperCase() + text.slice(1); // "setembro de 2026" -> "Setembro de 2026"
}

export function fmtDay(date: string): string {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString("pt-BR", {
    weekday: "short", day: "2-digit", month: "2-digit", timeZone: "UTC",
  });
}

export function fmtCpf(cpf: string): string {
  const d = cpf.replace(/\D/g, "");
  return d.length === 11 ? `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}` : cpf;
}

export function initials(name: string): string {
  const p = name.trim().split(/\s+/);
  return ((p[0]?.[0] ?? "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
}
