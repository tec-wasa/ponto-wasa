import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { IconBars, IconClock, IconHome, IconList, IconMoon, IconMore, IconPeople, IconSun } from "./icons";
import Account from "./pages/Account";
import Cadastros, { Empresa } from "./pages/Admin";
import Approvals from "./pages/Approvals";
import MyBank, { TeamBank } from "./pages/Bank";
import Diagnostic from "./pages/Diagnostic";
import Login from "./pages/Login";
import Mirror from "./pages/Mirror";
import More from "./pages/More";
import MyRequests from "./pages/MyRequests";
import Punch from "./pages/Punch";
import Reports from "./pages/Reports";
import Team from "./pages/Team";
import TeamAbsences from "./pages/TeamAbsences";
import { runSync } from "./sync";
import { applyTheme, currentTheme } from "./theme";
import type { Permission, User } from "./types";

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme());
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="icon-btn" aria-label={next === "dark" ? "Mudar para o tema escuro" : "Mudar para o tema claro"}
      onClick={() => { applyTheme(next); setTheme(next); }}>
      {theme === "dark" ? <IconMoon /> : <IconSun />}
    </button>
  );
}

export interface NavItem { to: string; label: string; hint: string; icon?: ReactNode; end?: boolean }

/** Os itens de cada área, conforme as permissões. É a única definição de menu (desktop, abas do celular e "Mais"). */
export function areaItems(can: (p: Permission) => boolean) {
  const mine: NavItem[] = can("punch") ? [
    { to: "/", label: "Ponto", hint: "Registrar entrada, intervalo e saída", icon: <IconHome />, end: true },
    { to: "/registros", label: "Registros", hint: "Espelho do mês e comprovantes", icon: <IconList /> },
    { to: "/solicitacoes", label: "Solicitações", hint: "Corrigir marcação, atestado ou abono", icon: <IconClock /> },
    { to: "/banco", label: "Banco de horas", hint: "Saldo e extrato" },
  ] : [];
  const team = can("team.view");
  const empresa = [
    can("closing.view") && "fechamento", (can("fiscal.export") || can("integrity.view")) && "fiscalização",
    can("company.settings") && "configurações", can("audit.view") && "auditoria",
  ].filter(Boolean) as string[];
  const mgmt: NavItem[] = [
    ...(team ? [{ to: "/gestao", label: "Painel", hint: "Quem está trabalhando agora", icon: <IconPeople />, end: true }] : []),
    ...(can("approvals") ? [{ to: "/gestao/aprovacoes", label: "Aprovações", hint: "Ajustes e ausências aguardando decisão", icon: <IconClock /> }] : []),
    ...(team ? [{ to: "/gestao/espelhos", label: "Espelhos", hint: "Espelho de ponto de cada pessoa", icon: <IconList /> }] : []),
    ...(team ? [{ to: "/gestao/banco", label: "Banco de horas", hint: "Saldos e lançamentos" }] : []),
    ...(team ? [{ to: "/gestao/ausencias", label: "Ausências", hint: "Atestados, férias, licenças e afastamentos" }] : []),
    ...(team ? [{ to: "/gestao/relatorios", label: "Relatórios", hint: "Fechamento mensal, banco de horas, ausências", icon: <IconBars /> }] : []),
    ...(can("people.list") && (can("people.manage") || can("kiosks.view")) ? [{ to: "/gestao/cadastros", label: "Cadastros", hint: "Pessoas, jornadas e centrais" }] : []),
    ...(empresa.length ? [{ to: "/gestao/empresa", label: "Empresa", hint: empresa.join(", ").replace(/^./, (c) => c.toUpperCase()) }] : []),
  ];
  return { mine, mgmt };
}

function TopBar({ user, area, both, children }: { user: User; area: "mine" | "mgmt"; both: boolean; children?: ReactNode }) {
  return (
    <header className="topbar">
      <Link to={area === "mgmt" ? "/gestao" : "/"} className="wordmark">Ponto</Link>
      {both && (
        <nav className="area-switch" aria-label="Área">
          <Link to="/" className={area === "mine" ? "on" : ""} aria-current={area === "mine" ? "page" : undefined}>Meu ponto</Link>
          <Link to="/gestao" className={area === "mgmt" ? "on" : ""} aria-current={area === "mgmt" ? "page" : undefined}>Gestão</Link>
        </nav>
      )}
      {children}
      <div className="topbar-actions">
        <ThemeToggle />
        <NavLink to="/conta" className="avatar" aria-label={`Minha conta: ${user.name}`}>{initials(user.name)}</NavLink>
      </div>
    </header>
  );
}

export default function App() {
  const { user, company, loading, logout, restriction, can } = useAuth();
  const online = useOnline();
  const location = useLocation();
  const uid = user?.id;
  const punches = can("punch");
  const ready = !!company && !restriction;
  const lastArea = useRef<"mine" | "mgmt">("mine"); // "Mais", "Minha conta" e "Diagnóstico" ficam na área de onde a pessoa veio

  // Marcações feitas sem internet: enviadas ao voltar a rede, ao abrir o app e a cada 30 s enquanto houver conexão.
  useEffect(() => {
    if (!uid || !ready || !punches) return;
    const go = () => void runSync(uid).catch(() => undefined);
    go();
    const t = setInterval(go, 30_000);
    window.addEventListener("online", go);
    document.addEventListener("visibilitychange", go);
    return () => {
      clearInterval(t);
      window.removeEventListener("online", go);
      document.removeEventListener("visibilitychange", go);
    };
  }, [uid, ready, punches]);

  if (loading) return <p className="center muted" role="status">Carregando…</p>;
  if (!user) {
    return (
      <Routes>
        <Route path="/diagnostico" element={<Diagnostic />} />
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }

  if (restriction) {
    // Pendência de segurança (senha temporária ou 2FA exigido): só a tela de conta, até resolver.
    return (
      <div className="shell">
        <header className="topbar">
          <span className="wordmark">Ponto</span>
          <div className="topbar-actions"><ThemeToggle /><button className="link" onClick={logout}>Sair</button></div>
        </header>
        <main><Account /></main>
      </div>
    );
  }

  if (!company) return <p className="center muted" role="status">Carregando…</p>; // nunca renderiza as telas sem a empresa

  const { mine, mgmt } = areaItems(can);
  const both = mine.length > 0 && mgmt.length > 0;
  const path = location.pathname;
  const neutral = ["/mais", "/conta", "/diagnostico"].includes(path);
  const area: "mine" | "mgmt" = mine.length === 0 ? "mgmt" : mgmt.length === 0 ? "mine"
    : neutral ? lastArea.current : path.startsWith("/gestao") ? "mgmt" : "mine";
  lastArea.current = area;
  const items = area === "mgmt" ? mgmt : mine;
  const home = mine.length ? "/" : mgmt[0]?.to ?? "/conta";
  // Celular: as três primeiras telas da área viram abas; o resto fica em "Mais".
  const tabs = items.filter((i) => i.icon).slice(0, 3);
  const moreActive = !tabs.some((t) => (t.end ? path === t.to : path.startsWith(t.to)));

  return (
    <div className="shell">
      <TopBar user={user} area={area} both={both}>
        <nav className="topnav" aria-label="Navegação principal">
          {items.map((i) => <NavLink key={i.to} to={i.to} end={i.end}>{i.label}</NavLink>)}
        </nav>
      </TopBar>
      {!online && punches && area === "mine" && (
        <p className="banner" role="status">
          Sem conexão. Você ainda pode registrar ponto: a marcação fica guardada e é enviada quando a internet voltar.
        </p>
      )}
      {!online && area === "mgmt" && <p className="banner" role="status">Sem conexão: as informações da gestão podem estar desatualizadas.</p>}
      <main>
        <Routes>
          {punches && <Route path="/" element={<Punch online={online} />} />}
          {punches && <Route path="/registros" element={<Mirror mode="self" />} />}
          {punches && <Route path="/solicitacoes" element={<MyRequests />} />}
          {punches && <Route path="/banco" element={<MyBank />} />}
          {can("team.view") && <Route path="/gestao" element={<Team />} />}
          {can("approvals") && <Route path="/gestao/aprovacoes" element={<Approvals />} />}
          {can("team.view") && <Route path="/gestao/espelhos" element={<Mirror mode="team" />} />}
          {can("team.view") && <Route path="/gestao/banco" element={<TeamBank />} />}
          {can("team.view") && <Route path="/gestao/ausencias" element={<TeamAbsences />} />}
          {can("team.view") && <Route path="/gestao/relatorios" element={<Reports />} />}
          {mgmt.some((i) => i.to === "/gestao/cadastros") && <Route path="/gestao/cadastros" element={<Cadastros />} />}
          {mgmt.some((i) => i.to === "/gestao/empresa") && <Route path="/gestao/empresa" element={<Empresa />} />}
          <Route path="/conta" element={<Account />} />
          <Route path="/diagnostico" element={<Diagnostic />} />
          <Route path="/mais" element={<More items={items.filter((i) => !tabs.includes(i))} area={area} both={both} onLogout={logout} />} />
          {/* endereços antigos */}
          <Route path="/espelho" element={<Navigate to={punches ? "/registros" : "/gestao/espelhos"} replace />} />
          <Route path="/ajustes" element={<Navigate to={can("approvals") && !punches ? "/gestao/aprovacoes" : "/solicitacoes"} replace />} />
          <Route path="/ausencias" element={<Navigate to={punches ? "/solicitacoes?tipo=ausencia" : "/gestao/ausencias"} replace />} />
          <Route path="/equipe" element={<Navigate to="/gestao" replace />} />
          <Route path="/relatorios" element={<Navigate to="/gestao/relatorios" replace />} />
          <Route path="/admin" element={<Navigate to="/gestao/cadastros" replace />} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </main>
      <nav className="tabbar" aria-label="Navegação principal">
        {tabs.map((t) => <NavLink key={t.to} to={t.to} end={t.end}>{t.icon}{t.label}</NavLink>)}
        <NavLink to="/mais" className={moreActive ? "active" : ""}><IconMore />Mais</NavLink>
      </nav>
    </div>
  );
}
