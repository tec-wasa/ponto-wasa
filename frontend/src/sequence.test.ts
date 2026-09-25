import { describe, expect, it } from "vitest";
import { type Rules, currentCycle, greeting, isDayClosed, nextKind, ordinal, remainingKinds, situation } from "./sequence";

const TZ = "America/Sao_Paulo"; // UTC-3
const END: Rules = { tz: TZ, crosses: false }; // padrão: a jornada se encerra à meia-noite
const CROSS: Rules = { tz: TZ, crosses: true }; // turno que pode terminar no dia seguinte
const NOW = Date.parse("2026-01-05T15:00:00Z"); // 12:00 local
const at = (kind: string, minutesAgo: number) => ({ kind, occurred_at: new Date(NOW - minutesAgo * 60_000).toISOString() });
const m = (kind: string, iso: string) => ({ kind, occurred_at: iso });

describe("nextKind", () => {
  it("segue a ordem completa com intervalo", () => {
    expect(nextKind(undefined, true, NOW, END)).toBe("entrada");
    expect(nextKind(at("entrada", 60), true, NOW, END)).toBe("inicio_intervalo");
    expect(nextKind(at("inicio_intervalo", 10), true, NOW, END)).toBe("fim_intervalo");
    expect(nextKind(at("fim_intervalo", 10), true, NOW, END)).toBe("saida");
    expect(nextKind(at("saida", 10), true, NOW, END)).toBe("entrada");
  });
  it("sem intervalo na jornada: entrada e saída", () => {
    expect(nextKind(at("entrada", 60), false, NOW, END)).toBe("saida");
  });
  it("com a opção de virar a meia-noite, marcação aberta há mais de 16 h recomeça em entrada", () => {
    expect(nextKind(at("entrada", 15 * 60), true, NOW, CROSS)).toBe("inicio_intervalo");
    expect(nextKind(at("entrada", 17 * 60), true, NOW, CROSS)).toBe("entrada");
  });
  it("padrão: entrada de ontem sem saída não continua hoje, mesmo dentro de 16 h", () => {
    expect(nextKind(at("entrada", 9 * 60), true, NOW, END)).toBe("inicio_intervalo"); // 03:00 local de hoje: mesmo dia
    const lastNight = m("entrada", "2026-01-05T02:00:00Z"); // 04/01 23:00 local
    expect(nextKind(lastNight, true, NOW, END)).toBe("entrada"); // outro dia: saída ausente, recomeça
    expect(nextKind(lastNight, true, NOW, CROSS)).toBe("inicio_intervalo"); // com a opção, o turno continua
  });
});

describe("ordinal e saudação", () => {
  it("numera as batidas do dia", () => {
    expect(["entrada", "inicio_intervalo", "fim_intervalo", "saida"].map((k) => ordinal(k as never, true))).toEqual([1, 2, 3, 4]);
    expect([ordinal("entrada", false), ordinal("saida", false)]).toEqual([1, 2]);
  });
  it("saúda conforme a hora", () => {
    expect([0, 5, 11, 12, 17, 18, 23].map(greeting)).toEqual(
      ["Bom dia", "Bom dia", "Bom dia", "Boa tarde", "Boa tarde", "Boa noite", "Boa noite"]);
  });
});

describe("currentCycle", () => {
  it("com a opção, turno aberto que começou ontem continua na lista de hoje", () => {
    const marks = [m("inicio_intervalo", "2026-03-12T03:30:00Z"), m("entrada", "2026-03-12T02:00:00Z")]; // 11/03 23:00 e 00:30 locais
    const now = Date.parse("2026-03-12T04:00:00Z"); // 12/03 01:00 local
    expect(currentCycle(marks, now, CROSS).map((x) => x.kind)).toEqual(["entrada", "inicio_intervalo"]);
  });
  it("padrão: o que ficou aberto na véspera não entra na lista de hoje", () => {
    const marks = [m("entrada", "2026-03-12T11:00:00Z"), m("entrada", "2026-03-12T02:00:00Z")]; // 12/03 08:00 e 11/03 23:00
    expect(currentCycle(marks, Date.parse("2026-03-12T13:00:00Z"), END).map((x) => x.occurred_at)).toEqual(["2026-03-12T11:00:00Z"]);
  });
  it("não mistura o turno anterior e some no dia seguinte ao encerrado", () => {
    const marks = [m("entrada", "2026-03-11T11:00:00Z"), m("saida", "2026-03-10T20:00:00Z"), m("entrada", "2026-03-10T11:00:00Z")];
    expect(currentCycle(marks, Date.parse("2026-03-11T13:00:00Z"), CROSS).map((x) => x.kind)).toEqual(["entrada"]);
    const closed = [m("saida", "2026-03-11T20:00:00Z"), m("entrada", "2026-03-11T11:00:00Z")];
    expect(currentCycle(closed, Date.parse("2026-03-11T22:00:00Z"), END)).toHaveLength(2);
    expect(currentCycle(closed, Date.parse("2026-03-12T12:00:00Z"), END)).toEqual([]);
    expect(currentCycle(closed, Date.parse("2026-03-12T12:00:00Z"), CROSS)).toEqual([]);
  });
});

describe("isDayClosed", () => {
  it("a saída do mesmo dia encerra a jornada", () => {
    const marks = [m("saida", "2026-03-11T20:00:00Z"), m("fim_intervalo", "2026-03-11T16:00:00Z"), m("inicio_intervalo", "2026-03-11T15:00:00Z"), m("entrada", "2026-03-11T11:00:00Z")];
    for (const rules of [END, CROSS]) {
      expect(isDayClosed(marks, Date.parse("2026-03-11T21:00:00Z"), rules)).toBe(true);
      expect(isDayClosed(marks.slice(1), Date.parse("2026-03-11T21:00:00Z"), rules)).toBe(false);
    }
  });
  it("turno da noite: com a opção não fecha o dia em que terminou; sem ela, a saída de hoje encerra", () => {
    const night = [m("saida", "2026-03-11T10:00:00Z"), m("entrada", "2026-03-11T02:00:00Z")]; // 10/03 23:00 -> 11/03 07:00 locais
    const now = Date.parse("2026-03-11T15:00:00Z");
    expect(isDayClosed(night, now, CROSS)).toBe(false);
    expect(isDayClosed(night, now, END)).toBe(true);
    const day = [m("saida", "2026-03-11T20:00:00Z"), m("entrada", "2026-03-11T11:00:00Z")];
    expect(isDayClosed(day, Date.parse("2026-03-12T12:00:00Z"), END)).toBe(false); // no dia seguinte recomeça
  });
});

describe("situation e linha do tempo", () => {
  it("classifica a situação atual", () => {
    expect(situation(at("entrada", 5), NOW, END)).toBe("working");
    expect(situation(at("fim_intervalo", 5), NOW, END)).toBe("working");
    expect(situation(at("inicio_intervalo", 5), NOW, END)).toBe("break");
    expect(situation(at("saida", 5), NOW, END)).toBe("off");
    expect(situation(undefined, NOW, END)).toBe("off");
    expect(situation(m("entrada", "2026-01-05T02:00:00Z"), NOW, END)).toBe("off"); // entrada de ontem: saída ausente
    expect(situation(m("entrada", "2026-01-05T02:00:00Z"), NOW, CROSS)).toBe("working");
  });
  it("lista o que falta até a saída", () => {
    expect(remainingKinds(undefined, true, NOW, END)).toEqual(["entrada", "inicio_intervalo", "fim_intervalo", "saida"]);
    expect(remainingKinds(at("entrada", 5), true, NOW, END)).toEqual(["inicio_intervalo", "fim_intervalo", "saida"]);
    expect(remainingKinds(at("entrada", 5), false, NOW, END)).toEqual(["saida"]);
    expect(remainingKinds(at("saida", 5), true, NOW, END)).toEqual([]);
    expect(remainingKinds(m("saida", "2026-01-04T20:00:00Z"), true, NOW, END)).toHaveLength(4); // saída de ontem: dia novo
  });
});
