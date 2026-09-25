import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { PWA_EVENT, install, isStandalone, pwa } from "../pwa";

interface Props { reports: boolean; admin: boolean; onLogout: () => void }

/** Tudo o que não cabe nas 4 abas do celular. */
export default function More({ reports, admin, onLogout }: Props) {
  const { user, company } = useAuth();
  const [, force] = useState(0);
  const [installMsg, setInstallMsg] = useState("");
  useEffect(() => {
    const f = () => force((n) => n + 1);
    window.addEventListener(PWA_EVENT, f);
    return () => window.removeEventListener(PWA_EVENT, f);
  }, []);
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const items = [
    { to: "/ajustes", title: "Ajustes", hint: "Pedir inclusão ou correção de marcação" },
    { to: "/ausencias", title: "Ausências", hint: "Atestados, abonos, férias e afastamentos" },
    { to: "/banco", title: "Banco de horas", hint: "Saldo e extrato" },
    ...(reports ? [{ to: "/relatorios", title: "Relatórios", hint: "Fechamento mensal, banco de horas e ausências" }] : []),
    ...(admin ? [{ to: "/admin", title: "Gestão", hint: "Colaboradores, jornadas, fechamento e fiscalização" }] : []),
    { to: "/conta", title: "Minha conta", hint: "Senha e verificação em duas etapas" },
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
          {items.map((i) => (
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
