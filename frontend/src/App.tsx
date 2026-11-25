import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { IconClock, IconHome, IconList, IconMoon, IconMore, IconPeople, IconSun } from "./icons";
import Absences from "./pages/Absences";
import Account from "./pages/Account";
import Adjustments from "./pages/Adjustments";
import Admin from "./pages/Admin";
import Bank from "./pages/Bank";
import Diagnostic from "./pages/Diagnostic";
import Login from "./pages/Login";
import Mirror from "./pages/Mirror";
import More from "./pages/More";
import Punch from "./pages/Punch";
import Reports from "./pages/Reports";
import Team from "./pages/Team";
import { runSync } from "./sync";
import { applyTheme, currentTheme } from "./theme";
import type { User } from "./types";

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

function TopBar({ user, children }: { user: User; children?: React.ReactNode }) {
  return (
    <header className="topbar">
      <NavLink to="/" className="wordmark">Ponto</NavLink>
      {children}
      <div className="topbar-actions">
        <ThemeToggle />
        <NavLink to="/conta" className="avatar" aria-label={`Minha conta: ${user.name}`}>{initials(user.name)}</NavLink>
      </div>
    </header>
  );
}

export default function App() {
  const { user, company, loading, logout, restriction } = useAuth();
  const online = useOnline();
  const location = useLocation();
  const uid = user?.id;
  const ready = !!company && !restriction;

  // Marcações feitas sem internet: enviadas ao voltar a rede, ao abrir o app e a cada 30 s enquanto houver conexão.
  useEffect(() => {
    if (!uid || !ready) return;
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
  }, [uid, ready]);

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

  const canAdmin = ["hr", "admin", "auditor"].includes(user.role);
  const approver = ["manager", "hr", "admin"].includes(user.role);
  const reports = approver || canAdmin;
  const tracks = user.tracks_time !== false; // cadastro só de gestão não bate ponto: sem a tela "Ponto"

  // Menu do desktop: tudo. Barra inferior do celular: 4 abas (design.md); o resto fica em "Mais".
  const desktop = [
    ...(tracks ? [{ to: "/", label: "Ponto", end: true }] : []), { to: "/espelho", label: "Espelho" }, { to: "/ajustes", label: "Ajustes" },
    { to: "/ausencias", label: "Ausências" }, { to: "/banco", label: "Banco de horas" },
    ...(approver ? [{ to: "/equipe", label: "Equipe" }] : []),
    ...(reports ? [{ to: "/relatorios", label: "Relatórios" }] : []),
    ...(canAdmin ? [{ to: "/admin", label: "Gestão" }] : []),
  ];
  const first = tracks ? { to: "/", label: "Ponto", icon: <IconHome /> } : { to: "/equipe", label: "Equipe", icon: <IconPeople /> };
  const third = approver && tracks ? { to: "/equipe", label: "Equipe", icon: <IconPeople /> } : { to: "/banco", label: "Banco", icon: <IconClock /> };
  const tabPaths = [first.to, "/espelho", third.to];
  const moreActive = !tabPaths.includes(location.pathname);

  return (
    <div className="shell">
      <TopBar user={user}>
        <nav className="topnav" aria-label="Navegação principal">
          {desktop.map((i) => <NavLink key={i.to} to={i.to} end={i.end}>{i.label}</NavLink>)}
        </nav>
      </TopBar>
      {!online && (
        <p className="banner" role="status">
          Sem conexão. Você ainda pode registrar ponto: a marcação fica guardada e é enviada quando a internet voltar.
        </p>
      )}
      <main>
        <Routes>
          <Route path="/" element={tracks ? <Punch online={online} /> : <Navigate to={approver ? "/equipe" : "/admin"} replace />} />
          <Route path="/espelho" element={<Mirror />} />
          <Route path="/ajustes" element={<Adjustments />} />
          <Route path="/ausencias" element={<Absences />} />
          <Route path="/conta" element={<Account />} />
          <Route path="/banco" element={<Bank />} />
          <Route path="/diagnostico" element={<Diagnostic />} />
          <Route path="/mais" element={<More reports={reports} admin={canAdmin} onLogout={logout} />} />
          {approver && <Route path="/equipe" element={<Team />} />}
          {reports && <Route path="/relatorios" element={<Reports />} />}
          {canAdmin && <Route path="/admin" element={<Admin />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <nav className="tabbar" aria-label="Navegação principal">
        <NavLink to={first.to} end>{first.icon}{first.label}</NavLink>
        <NavLink to="/espelho"><IconList />Registros</NavLink>
        <NavLink to={third.to}>{third.icon}{third.label}</NavLink>
        <NavLink to="/mais" className={moreActive ? "active" : ""}><IconMore />Mais</NavLink>
      </nav>
    </div>
  );
}

