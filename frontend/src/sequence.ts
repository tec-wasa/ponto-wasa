import { parseUtc } from "./util";

/** Ordem das marcações: entrada, intervalo, retorno do intervalo, saída. Espelha `punching.py` do servidor. */
export type Kind = "entrada" | "inicio_intervalo" | "fim_intervalo" | "saida";

export const SLOT_LABEL: Record<Kind, string> = {
  entrada: "Entrada",
  inicio_intervalo: "Intervalo",
  fim_intervalo: "Retorno do intervalo",
  saida: "Saída",
};

const SIXTEEN_HOURS = 16 * 3600 * 1000;

export interface Mark {
  kind: string;
  occurred_at: string;
}

/** Regras da jornada da pessoa. Padrão (`crosses: false`): o turno se encerra à meia-noite, e uma entrada sem saída fica
 * como "saída ausente" (o dia seguinte recomeça em entrada). `crosses: true`: o turno pode terminar no dia seguinte. */
export interface Rules {
  tz: string;
  crosses: boolean;
}

const dayOf = (iso: string, tz: string) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(parseUtc(iso));
const nowDay = (now: number, tz: string) => dayOf(new Date(now).toISOString(), tz);

/** Há um turno em aberto? Vale por até 16 h e, sem a opção "vira a meia-noite", só no mesmo dia local. */
function openShift(last: Mark | undefined, now: number, rules: Rules): boolean {
  if (!last || last.kind === "saida" || now - parseUtc(last.occurred_at).getTime() > SIXTEEN_HOURS) return false;
  return rules.crosses || dayOf(last.occurred_at, rules.tz) === nowDay(now, rules.tz);
}

/** Tipo da próxima marcação. Turno não aberto (esquecido, ou de outro dia sem a opção): recomeça em entrada. */
export function nextKind(last: Mark | undefined, hasBreak: boolean, now: number, rules: Rules): Kind {
  if (!openShift(last, now, rules)) return "entrada";
  if (last!.kind === "inicio_intervalo") return "fim_intervalo";
  if (last!.kind === "fim_intervalo") return "saida";
  return hasBreak ? "inicio_intervalo" : "saida"; // última = entrada
}

/** Número da batida no dia (1ª entrada, 2ª intervalo, 3ª retorno, 4ª saída). Sem intervalo na jornada: 1ª entrada, 2ª saída. */
export function ordinal(kind: Kind, hasBreak: boolean): number {
  return (hasBreak ? ["entrada", "inicio_intervalo", "fim_intervalo", "saida"] : ["entrada", "saida"]).indexOf(kind) + 1;
}

/** Saudação pelo horário local (0-11 bom dia, 12-17 boa tarde, demais boa noite). */
export function greeting(hour: number): string {
  return hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";
}

/** A jornada de hoje terminou? (`marks` da mais nova para a mais antiga.) Espelha `punching.day_closed`: a última marcação é
 * uma saída, e a saída é definitiva (não há quinta batida). Padrão: vale se a saída é de hoje. Com a opção "vira a
 * meia-noite": vale se o turno começou hoje (quem saiu às 07h pode abrir outro turno à noite). */
export function isDayClosed(marks: Mark[], now: number, rules: Rules): boolean {
  const last = marks[0];
  if (!last || last.kind !== "saida") return false;
  if (!rules.crosses) return dayOf(last.occurred_at, rules.tz) === nowDay(now, rules.tz);
  const start = marks.slice(1, 6).find((m) => m.kind === "entrada");
  return dayOf((start ?? last).occurred_at, rules.tz) === nowDay(now, rules.tz);
}

/** O turno que está valendo agora, em ordem cronológica. Padrão: só as marcações de hoje desde a última saída (o que
 * ficou aberto ontem é "saída ausente" e não entra). Com a opção "vira a meia-noite": todo o turno aberto, mesmo que
 * tenha começado ontem. Turno encerrado só aparece no dia da saída. `marks`: da mais nova para a mais antiga. */
export function currentCycle<T extends Mark>(marks: T[], now: number, rules: Rules): T[] {
  const cycle: T[] = [];
  for (let i = 0; i < marks.length; i++) {
    const m = marks[i];
    if (i > 0 && m.kind === "saida") break; // saída anterior: é de outro turno
    if (cycle.length) {
      const prev = cycle[cycle.length - 1];
      if (parseUtc(prev.occurred_at).getTime() - parseUtc(m.occurred_at).getTime() > SIXTEEN_HOURS) break;
      if (!rules.crosses && dayOf(m.occurred_at, rules.tz) !== dayOf(prev.occurred_at, rules.tz)) break; // meia-noite corta
    }
    cycle.push(m);
  }
  const newest = cycle[0];
  if (!newest) return [];
  const today = dayOf(newest.occurred_at, rules.tz) === nowDay(now, rules.tz);
  const alive =
    newest.kind === "saida" || !rules.crosses
      ? today && (newest.kind === "saida" || now - parseUtc(newest.occurred_at).getTime() <= SIXTEEN_HOURS)
      : now - parseUtc(newest.occurred_at).getTime() <= SIXTEEN_HOURS;
  return alive ? cycle.reverse() : [];
}

export type Situation = "working" | "break" | "off";

/** Onde a pessoa está agora, a partir da última marcação. */
export function situation(last: Mark | undefined, now: number, rules: Rules): Situation {
  if (!openShift(last, now, rules)) return "off";
  return last!.kind === "inicio_intervalo" ? "break" : "working";
}

/** O que ainda falta na jornada depois da última marcação (para a linha do tempo), até a saída. */
export function remainingKinds(last: Mark | undefined, hasBreak: boolean, now: number, rules: Rules): Kind[] {
  if (last?.kind === "saida" && dayOf(last.occurred_at, rules.tz) === nowDay(now, rules.tz)) return [];
  const out: Kind[] = [];
  let cursor: Mark | undefined = last;
  for (let i = 0; i < 4; i++) {
    const k = nextKind(cursor, hasBreak, now, rules);
    out.push(k);
    if (k === "saida") break;
    cursor = { kind: k, occurred_at: new Date(now).toISOString() };
  }
  return out;
}
