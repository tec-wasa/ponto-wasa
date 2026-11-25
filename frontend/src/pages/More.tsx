import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import type { NavItem } from "../App";
import { useAuth } from "../auth";
import { PWA_EVENT, install, isStandalone, pwa } from "../pwa";

interface Props { items: NavItem[]; area: "mine" | "mgmt"; both: boolean; onLogout: () => void }

/** Tudo o que não cabe nas abas do celular, da área atual. */
export default function More({ items, area, both, onLogout }: Props) {
  const { user, company } = useAuth();
  const [, force] = useState(0);
  const [installMsg, setInstallMsg] = useState("");
  useEffect(() => {
    const f = () => force((n) => n + 1);
    window.addEventListener(PWA_EVENT, f);
    return () => window.removeEventListener(PWA_EVENT, f);
  }, []);
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const list = [
    ...items.map((i) => ({ to: i.to, title: i.label, hint: i.hint })),
    ...(both ? [area === "mine"
      ? { to: "/gestao", title: "Ir para a Gestão", hint: "Equipe, aprovações, cadastros" }
      : { to: "/", title: "Ir para Meu ponto", hint: "Registrar o meu ponto e ver os meus registros" }] : []),
    { to: "/conta", title: "Minha conta", hint: "Dados de acesso e segurança" },
    { to: "/ajuda", title: "Ajuda", hint: "Manual: onde fica, o que é e como fazer cada coisa" },
    { to: "/diagnostico", title: "Diagnóstico do aplicativo", hint: "Por que o app instala (ou não) e se funciona sem internet" },
  ];
  return (
    <>
      <h1>Mais</h1>
      <p className="muted small">{user?.name} · {company?.name}</p>
      {!isStandalone() && (
        <section className="card">
          <h2 className="section-title">Instalar o aplicativo</h2>
          {pwa.prompt ? (
            <button className="primary" style={{ width: "100%" }} onClick={async () => setInstallMsg((await install()) === "accepted" ? "Instalado!" : "")}>Instalar aplicativo</button>
          ) : ios ? (
            <p className="muted small" style={{ margin: 0 }}>No iPhone: toque em Compartilhar e depois em “Adicionar à Tela de Início”.</p>
          ) : (
            <p className="muted small" style={{ margin: 0 }}>O navegador ainda não liberou a instalação. Abra o Diagnóstico abaixo para ver o motivo.</p>
          )}
          {installMsg && <p className="alert ok" role="status" style={{ marginTop: 12 }}>{installMsg}</p>}
        </section>
      )}
      <section className="card" style={{ padding: "4px 16px" }}>
        <ul className="more-list">
          {list.map((i) => (
            <li key={i.to}>
              <Link to={i.to}><span>{i.title}<small>{i.hint}</small></span><span aria-hidden="true">›</span></Link>
            </li>
          ))}
          <li><button className="row-btn" onClick={onLogout}>Sair</button></li>
        </ul>
      </section>
    </>
  );
}
