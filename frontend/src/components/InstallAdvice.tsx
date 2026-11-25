import { useState } from "react";
import { browserKind, chromeIntentUrl } from "../browser";

const APP_URL = () => window.location.origin;

/** Orientação de instalação conforme o navegador que abriu o app. `compact` mostra só o essencial (tela de entrada). */
export default function InstallAdvice({ compact = false }: { compact?: boolean }) {
  const kind = browserKind();
  const [copied, setCopied] = useState(false);
  const android = /android/i.test(navigator.userAgent);

  async function copy() {
    try {
      await navigator.clipboard.writeText(APP_URL());
      setCopied(true);
    } catch {
      window.prompt("Copie o endereço:", APP_URL());
    }
  }

  const copyBtn = <button type="button" onClick={copy}>{copied ? "Endereço copiado" : "Copiar endereço"}</button>;

  if (kind === "in-app") {
    return (
      <div className="alert info" role="note">
        <p style={{ margin: "0 0 8px" }}>
          <b>Você abriu o Ponto dentro de outro aplicativo</b> (WhatsApp, Instagram, e-mail…). Por aqui ele não instala e
          não funciona sem internet. Abra no {android ? "Chrome" : "Safari"}:
        </p>
        {android ? (
          <div className="row"><a className="button primary" href={chromeIntentUrl()}>Abrir no Chrome</a>{copyBtn}</div>
        ) : (
          <>
            {!compact && <p className="small" style={{ margin: "0 0 8px" }}>Toque no menu (⋯ ou o ícone de bússola) e escolha <b>Abrir no Safari</b>. Se não houver essa opção, copie o endereço e cole no Safari.</p>}
            <div className="row">{copyBtn}</div>
          </>
        )}
      </div>
    );
  }
  if (compact) return null;

  const steps: Record<Exclude<typeof kind, "in-app">, string> = {
    "ios-safari": "Toque em Compartilhar (quadrado com seta para cima) > Adicionar à Tela de Início > Adicionar.",
    "ios-other": "No iPhone, instale pelo Safari: copie o endereço, abra no Safari e toque em Compartilhar > Adicionar à Tela de Início. (Em iOS 16.4 ou mais novo também funciona pelo Compartilhar deste navegador.)",
    "android-chrome": "Toque no menu ⋮ do Chrome > Instalar app (ou Adicionar à tela inicial > Instalar).",
    "android-samsung": "Toque no menu ☰ da Internet Samsung > Adicionar página a > Tela de início. Se não funcionar, abra no Chrome.",
    "android-firefox": "Toque no menu ⋮ do Firefox > Instalar (ou Adicionar à tela inicial). Se não funcionar, abra no Chrome.",
    "android-other": "Este navegador pode não instalar aplicativos da web. Abra no Chrome e instale pelo menu ⋮ > Instalar app.",
    desktop: "No Chrome ou no Edge, clique no ícone de instalar na barra de endereço, ou no menu > Instalar.",
  };
  return (
    <div>
      <p className="muted small" style={{ margin: 0 }}>{steps[kind]}</p>
      {(kind === "android-other" || kind === "android-samsung" || kind === "android-firefox") && (
        <div className="row" style={{ marginTop: 8 }}><a className="button" href={chromeIntentUrl()}>Abrir no Chrome</a></div>
      )}
      {kind === "ios-other" && <div className="row" style={{ marginTop: 8 }}>{copyBtn}</div>}
    </div>
  );
}
