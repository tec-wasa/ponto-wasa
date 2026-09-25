import { describe, expect, it } from "vitest";
import { fmtMinutes, localToUtcIso, parseUtc, shiftMonth } from "./util";

describe("util", () => {
  it("formata minutos", () => {
    expect(fmtMinutes(485)).toBe("8h05");
    expect(fmtMinutes(-30)).toBe("-0h30");
    expect(fmtMinutes(0)).toBe("0h00");
  });

  it("converte hora local de São Paulo para UTC", () => {
    expect(localToUtcIso("2026-08-03", "08:00", "America/Sao_Paulo")).toBe("2026-08-03T11:00:00.000Z");
    expect(localToUtcIso("2026-08-03", "23:30", "America/Sao_Paulo")).toBe("2026-08-04T02:30:00.000Z");
  });

  it("respeita horário de verão em outros fusos", () => {
    expect(localToUtcIso("2026-07-01", "12:00", "Europe/Lisbon")).toBe("2026-07-01T11:00:00.000Z");
    expect(localToUtcIso("2026-01-15", "12:00", "Europe/Lisbon")).toBe("2026-01-15T12:00:00.000Z");
  });

  it("interpreta datas da API como UTC", () => {
    expect(parseUtc("2026-08-03T11:00:00").toISOString()).toBe("2026-08-03T11:00:00.000Z");
    expect(parseUtc("2026-08-03T11:00:00Z").toISOString()).toBe("2026-08-03T11:00:00.000Z");
  });

  it("navega entre meses", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });
});
