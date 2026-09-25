export type Theme = "light" | "dark";

const KEY = "ponto.theme";

export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function currentTheme(): Theme {
  const a = document.documentElement.getAttribute("data-theme");
  return a === "dark" || a === "light" ? a : systemTheme();
}

export function applyTheme(t: Theme): void {
  document.documentElement.setAttribute("data-theme", t);
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* sem armazenamento: vale só nesta sessão */
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "dark" ? "#14171A" : "#F6F3EC");
}

/** Reaplica a escolha guardada (se houver); sem escolha, o CSS segue o tema do sistema. */
export function initTheme(): void {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") applyTheme(saved);
  } catch {
    /* ignora */
  }
}
