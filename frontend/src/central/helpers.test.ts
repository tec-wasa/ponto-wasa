import { describe, expect, it } from "vitest";
import { friendly, hideDigits, looksLikePontoQr, maskCpf, validIdentifier, validPin, WedgeBuffer } from "./helpers";

describe("máscaras e validações da Central", () => {
  it("formata o CPF conforme se digita", () => {
    expect(maskCpf("1")).toBe("1");
    expect(maskCpf("1234")).toBe("123.4");
    expect(maskCpf("1234567")).toBe("123.456.7");
    expect(maskCpf("12345678909")).toBe("123.456.789-09");
    expect(maskCpf("123456789091234")).toBe("123.456.789-09"); // ignora o excesso
  });
  it("esconde tudo menos os 3 últimos dígitos", () => {
    expect(hideDigits("12345678909")).toBe("••••••••909");
    expect(hideDigits("123")).toBe("123");
  });
  it("valida tamanho de código, CPF e PIN", () => {
    expect(validIdentifier("code", "1234")).toBe(true);
    expect(validIdentifier("code", "123")).toBe(false);
    expect(validIdentifier("code", "123456789")).toBe(false);
    expect(validIdentifier("cpf", "123.456.789-09")).toBe(true);
    expect(validIdentifier("cpf", "1234567890")).toBe(false);
    expect(["123", "1234", "123456", "1234567", "12a4"].map(validPin)).toEqual([false, true, true, false, false]);
  });
  it("só aceita QR do Ponto", () => {
    expect(looksLikePontoQr("PB1.1.5.1.0123456789abcdef0123")).toBe(true);
    expect(looksLikePontoQr("PR1.5.123456")).toBe(true);
    expect(looksLikePontoQr("https://exemplo.com")).toBe(false);
    expect(looksLikePontoQr("PR1.5.12345")).toBe(false);
  });
  it("traduz os erros mais comuns", () => {
    expect(friendly(409, "x", "day_closed")).toContain("Jornada encerrada");
    expect(friendly(0, "x")).toContain("Sem conexão");
    expect(friendly(401, "Código ou PIN incorreto")).toBe("Código ou PIN incorreto");
  });
});

describe("WedgeBuffer (leitor USB em modo teclado)", () => {
  const scan = (b: WedgeBuffer, text: string, start = 1000, gap = 5) => {
    let out: string | null = null;
    [...text, "Enter"].forEach((k, i) => { out = b.feed(k, start + i * gap) ?? out; });
    return out;
  };
  it("devolve o QR lido por um leitor rápido", () => {
    expect(scan(new WedgeBuffer(), "PR1.7.123456")).toBe("PR1.7.123456");
  });
  it("ignora digitação humana (teclas espaçadas)", () => {
    expect(scan(new WedgeBuffer(), "PR1.7.123456", 1000, 400)).toBeNull();
  });
  it("ignora Enter sozinho e textos curtos", () => {
    const b = new WedgeBuffer();
    expect(b.feed("Enter", 1)).toBeNull();
    expect(scan(b, "1234", 5000)).toBeNull();
  });
  it("uma leitura não contamina a seguinte", () => {
    const b = new WedgeBuffer();
    expect(scan(b, "PR1.7.111111", 1000)).toBe("PR1.7.111111");
    expect(scan(b, "PR1.7.222222", 9000)).toBe("PR1.7.222222");
  });
});
