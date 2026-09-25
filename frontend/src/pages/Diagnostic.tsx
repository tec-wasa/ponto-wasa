import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PWA_EVENT, isStandalone, pwa } from "../pwa";

interface Check {
  label: string;
  ok: boolean | null; // null = informativo
  detail: string;
}

/** Nenhuma verificação pode travar a tela: passou de 4 s, vale como "sem resposta". */
function guard<T>(p: Promise<T>, fallback: T, ms = 4000): Promise<T> {
  return Promise.race([p.catch(() => fallback), new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms))]);
}

async function head(url: string): Promise<{ ok: boolean; type: string; status: number }> {
  try {
    const r = await guard(fetch(url, { cache: "no-store" }), null as Response | null);
    if (!r) return { ok: false, type: "", status: 0 };
    return { ok: r.ok, type: r.headers.get("content-type") ?? "", status: r.status };
  } catch {
    return { ok: false, type: "", status: 0 };
  }
}

/** Mostra por que o navegador aceita ou recusa instalar o app: cada exigência do Chrome, uma linha. */
export default function Diagnostic() {
  const [checks, setChecks] = useState<Check[]>([]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const again = () => setTick((n) => n + 1);
    window.addEventListener(PWA_EVENT, again);
    return () => window.removeEventListener(PWA_EVENT, again);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const out: Check[] = [];
      const add = (label: string, ok: boolean | null, detail: string) => out.push({ label, ok, detail });

      add("Endereço seguro (HTTPS)", window.isSecureContext, `${location.protocol}//${location.host} — o Chrome só instala em HTTPS (ou localhost)`);
      add("Aberto como aplicativo instalado", null, isStandalone() ? "Sim: já está instalado" : "Não: aberto no navegador");

      const swSupported = "serviceWorker" in navigator;
      add("Service worker suportado", swSupported, swSupported ? "Sim" : "Este navegador/contexto não oferece service worker");
      if (swSupported) {
        const reg = await guard(navigator.serviceWorker.getRegistration("/"), undefined);
        const state = reg ? (reg.active ? `ativo (${reg.active.state})` : reg.installing ? "instalando…" : reg.waiting ? "aguardando" : "registrado") : "não registrado";
        add("Service worker registrado", !!reg?.active, pwa.swError ? `${state}. Erro ao registrar: ${pwa.swError}` : state);
        add("Service worker controla esta página", !!navigator.serviceWorker.controller, navigator.serviceWorker.controller ? "Sim" : "Não ainda: recarregue a página uma vez");
      }
      try {
        const names = await guard(caches.keys(), [] as string[]);
        const shell = names.find((n) => n.startsWith("ponto-shell-"));
        const count = shell ? (await guard((async () => (await (await caches.open(shell)).keys()).length)(), 0)) : 0;
        add("Aplicativo guardado para uso sem internet", count > 10, shell ? `${shell}: ${count} arquivos` : "Nenhum cache do aplicativo ainda");
      } catch {
        add("Aplicativo guardado para uso sem internet", false, "Cache indisponível neste contexto");
      }

      const m = await head("/manifest.webmanifest");
      add("Manifesto do aplicativo", m.ok && /json/.test(m.type), `HTTP ${m.status} ${m.type}`);
      if (m.ok) {
        try {
          const manifest = await (await fetch("/manifest.webmanifest", { cache: "no-store" })).json();
          add("Manifesto: nome, início e modo", !!manifest.name && !!manifest.start_url && ["standalone", "fullscreen", "minimal-ui"].includes(manifest.display),
            `${manifest.name} · start_url ${manifest.start_url} · ${manifest.display}`);
          for (const icon of manifest.icons ?? []) {
            const r = await head(icon.src);
            add(`Ícone ${icon.sizes} (${icon.purpose ?? "any"})`, r.ok && r.type.startsWith("image/"), `${icon.src}: HTTP ${r.status} ${r.type}`);
          }
        } catch {
          add("Manifesto legível", false, "Não é um JSON válido (um proxy pode estar devolvendo outra página)");
        }
      }
      add("Instalação oferecida pelo navegador", pwa.prompt ? true : null,
        pwa.prompt ? "Sim: o botão “Instalar aplicativo” (em Mais) funciona" : "O navegador ainda não ofereceu (ou já está instalado, ou algum item acima falhou)");
      if (alive) setChecks(out);
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  return (
    <main style={{ maxWidth: 640 }}>
      <h1>Diagnóstico do aplicativo</h1>
      <p className="muted small">Cada linha é uma exigência para instalar o app e usá-lo sem internet. Se alguma estiver vermelha, é ela o motivo.</p>
      <section className="card" style={{ padding: "4px 16px" }}>
        <ul className="plain">
          {checks.length === 0 && <li className="muted">Verificando…</li>}
          {checks.map((c) => (
            <li key={c.label} className="request" style={{ padding: "12px 0" }}>
              <strong>
                <span className={`dot ${c.ok === true ? "working" : c.ok === false ? "danger" : ""}`} style={{ display: "inline-block", marginRight: 8 }} aria-hidden="true" />
                {c.label}
                <span className="sr-only">{c.ok === true ? ": ok" : c.ok === false ? ": problema" : ""}</span>
              </strong>
              <span className="muted small" style={{ wordBreak: "break-word" }}>{c.detail}</span>
            </li>
          ))}
        </ul>
      </section>
      <button onClick={() => setTick(tick + 1)}>Verificar de novo</button>
      <p><Link to="/">Voltar</Link></p>
    </main>
  );
}
