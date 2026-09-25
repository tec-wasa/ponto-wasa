import { describe, expect, it } from "vitest";
import { type Bar, weekDates, withOpenTime } from "./PunchSide";

describe("weekDates", () => {
  it("vai de segunda a domingo, de qualquer dia da semana", () => {
    const week = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"];
    for (const day of week) expect(weekDates(day)).toEqual(week);
  });
  it("atravessa a virada do mês", () => {
    expect(weekDates("2026-09-30")).toEqual(["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
  });
});

describe("withOpenTime", () => {
  const bars: Bar[] = ["2026-09-24", "2026-09-25"].map((date) => ({ date, label: "x", worked: 60, expected: 480, partial: false, today: false }));
  it("soma o turno em andamento ao dia em que ele começou (fuso da empresa)", () => {
    const r = withOpenTime(bars, { since: "2026-09-25T11:00:00Z", minutes: 90 }, "America/Sao_Paulo"); // 25/09 08:00 local
    expect(r.map((b) => b.worked)).toEqual([60, 150]);
    expect(r[1].partial).toBe(true);
    // turno que começou na véspera à noite (23:00 local do dia 24) conta no dia 24
    expect(withOpenTime(bars, { since: "2026-09-25T02:00:00Z", minutes: 30 }, "America/Sao_Paulo").map((b) => b.worked)).toEqual([90, 60]);
  });
  it("sem turno em andamento nada muda", () => {
    expect(withOpenTime(bars, undefined, "America/Sao_Paulo")).toBe(bars);
    expect(withOpenTime(bars, { since: "2026-09-25T11:00:00Z", minutes: 0 }, "America/Sao_Paulo")).toBe(bars);
  });
});
