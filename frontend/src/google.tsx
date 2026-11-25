import { useEffect, useRef, useState } from "react";
import { currentTheme } from "./theme";

/** Configuração pública do servidor (Client ID do Google e quem opera o serviço). */
export interface PublicConfig { google_client_id: string | null; provider_name: string | null; provider_email: string | null }

let configPromise: Promise<PublicConfig> | null = null;
export function loadConfig(): Promise<PublicConfig> {
  configPromise ??= fetch("/api/auth/config").then((r) => (r.ok ? r.json() : Promise.reject())).catch(() => {
    configPromise = null;
    return { google_client_id: null, provider_name: null, provider_email: null };
  });
  return configPromise;
}

export function useConfig(): PublicConfig | null {
  const [c, setC] = useState<PublicConfig | null>(null);
  useEffect(() => { void loadConfig().then(setC); }, []);
  return c;
}

interface Gsi {
  accounts: { id: {
    initialize: (o: Record<string, unknown>) => void;
    renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
    disableAutoSelect: () => void;
  } };
}
declare global { interface Window { google?: Gsi } }

let gsiPromise: Promise<Gsi> | null = null;
function loadGsi(): Promise<Gsi> {
  gsiPromise ??= new Promise<Gsi>((resolve, reject) => {
    if (window.google?.accounts) return resolve(window.google);
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => (window.google ? resolve(window.google) : reject(new Error("Google indisponível")));
    s.onerror = () => { gsiPromise = null; reject(new Error("Não foi possível carregar o login do Google (sem internet?)")); };
    document.head.appendChild(s);
  });
  return gsiPromise;
}

/** Botão oficial "Fazer login com o Google". `onCredential` recebe o token assinado pelo Google, que o servidor confere. */
export function GoogleButton({ clientId, onCredential, text = "signin_with" }: {
  clientId: string; onCredential: (credential: string) => void; text?: "signin_with" | "continue_with";
}) {
  const box = useRef<HTMLDivElement>(null);
  const cb = useRef(onCredential);
  cb.current = onCredential;
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    loadGsi().then((g) => {
      if (!alive || !box.current) return;
      g.accounts.id.initialize({
        client_id: clientId, callback: (r: { credential: string }) => cb.current(r.credential),
        ux_mode: "popup", auto_select: false, cancel_on_tap_outside: true, itp_support: true,
      });
      g.accounts.id.renderButton(box.current, {
        type: "standard", theme: currentTheme() === "dark" ? "filled_black" : "outline", size: "large", text, shape: "pill",
        logo_alignment: "left", locale: "pt-BR", width: Math.min(360, box.current.clientWidth || 320),
      });
    }).catch((e) => alive && setError(e instanceof Error ? e.message : "Login do Google indisponível"));
    return () => { alive = false; };
  }, [clientId, text]);

  return (
    <>
      <div ref={box} style={{ display: "flex", justifyContent: "center", minHeight: 44, width: "100%" }} />
      {error && <p className="muted small" style={{ textAlign: "center" }}>{error}</p>}
    </>
  );
}

/** Ao sair: o Google não faz login automático de novo neste aparelho. */
export function googleSignOut() {
  window.google?.accounts.id.disableAutoSelect();
}
