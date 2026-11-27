import { describe, expect, it } from "vitest";
import { fmtAmount } from "./Payroll";

describe("fmtAmount", () => {
  it("mostra horas centesimais como h:mm e dias como número", () => {
    expect(fmtAmount(10.5, "horas")).toBe("10h30");
    expect(fmtAmount(2, "horas")).toBe("2h00");
    expect(fmtAmount(0.25, "horas")).toBe("0h15");
    expect(fmtAmount(3, "dias")).toBe("3");
    expect(fmtAmount(0, "horas")).toBe("");
    expect(fmtAmount(undefined, "dias")).toBe("");
  });
});
