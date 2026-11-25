/** Estado da instalação do app (PWA). Registrado cedo para não perder o evento de instalação. */
interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export const pwa = {
  prompt: null as InstallPromptEvent | null,
  swError: "",
  installed: false,
};

export const PWA_EVENT = "ponto:pwa";
const notify = () => window.dispatchEvent(new Event(PWA_EVENT));

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); // o botão "Instalar aplicativo" (Mais) usa este evento
  pwa.prompt = e as InstallPromptEvent;
  notify();
});
window.addEventListener("appinstalled", () => {
  pwa.installed = true;
  pwa.prompt = null;
  notify();
});

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    // Pede ao navegador para não apagar os dados do app (batidas guardadas sem internet) quando faltar espaço.
    void navigator.storage?.persist?.().catch(() => false);
    navigator.serviceWorker.register("/sw.js").catch((e) => {
      pwa.swError = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      notify();
    });
  });
}

export async function install(): Promise<"accepted" | "dismissed" | "unavailable"> {
  if (!pwa.prompt) return "unavailable";
  await pwa.prompt.prompt();
  const { outcome } = await pwa.prompt.userChoice;
  pwa.prompt = null;
  notify();
  return outcome;
}

export const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
