import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ROLE_LABEL, initials } from "../util";
import { GoogleButton, googleSignOut, useConfig } from "../google";
import MyBadge from "./MyBadge";

interface Tokens { access_token: string; refresh_token: string }

export default function Account() {
  const { user, company, restriction, twoFactor, can, logout } = useAuth();
  const passwords = company?.password_login !== false || !!restriction; // a empresa pode deixar só o Google
  const funcs = (user?.roles ?? []).filter((r) => r !== "auditor").map((r) => ROLE_LABEL[r]);
  const who = [...funcs, ...(can("punch") ? [] : ["não registra ponto"])].join(" · ") || "Colaborador";
  const forced = restriction === "password_change_required";
  return (
    <>
      <h1>Minha conta</h1>
      {forced && (
        <p className="alert error" role="alert">
          Você entrou com uma senha temporária. Crie uma senha nova para continuar.
        </p>
      )}
      {restriction === "two_factor_required" && (
        <p className="alert error" role="alert">
          Seu perfil exige verificação em duas etapas. Ative-a abaixo para continuar.
        </p>
      )}
      <section className="card profile">
        <span className="avatar big" aria-hidden="true">{initials(user?.name ?? "")}</span>
        <div>
          <strong>{user?.name}</strong>
          <div className="muted small">{user?.email}</div>
          <div className="muted small">{who}{company ? ` · ${company.name}` : ""}</div>
        </div>
      </section>

      {!restriction && <SignIn />}

      {passwords && restriction !== "two_factor_required" && (
        <details className="fold" open={forced}>
          <summary>Trocar a senha</summary>
          <ChangePassword />
        </details>
      )}
      {restriction !== "password_change_required" && (
        <>
          <p className="section-title" style={{ marginTop: 20 }}>
            Segurança{twoFactor?.enabled ? " · 2FA ativo" : ""}
          </p>
          {passwords && <TwoFactor />}
          {can("punch") && <MyBadge />}
        </>
      )}
      <button style={{ width: "100%", marginTop: 20 }} onClick={() => { googleSignOut(); logout(); }}>Sair</button>
    </>
  );
}

/** Como a pessoa entra: conta Google vinculada (ou não) e, se a empresa permitir, e-mail e senha. */
function SignIn() {
  const { user, company, reload } = useAuth();
  const config = useConfig();
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  if (!config?.google_client_id) return null;

  async function link(credential: string) {
    try {
      await api("/auth/google/link", { method: "POST", body: { credential } });
      await reload();
      setMsg({ type: "ok", text: "Conta Google vinculada. Da próxima vez, use “Entrar com Google”." });
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  async function unlink() {
    try {
      await api("/auth/google/unlink", { method: "POST" });
      await reload();
      setConfirm(false);
      setMsg({ type: "ok", text: "Conta Google desvinculada." });
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  return (
    <section className="card" aria-labelledby="h-entrar">
      <h2 id="h-entrar" className="section-title">Como você entra</h2>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      {user?.google_linked ? (
        <>
          <p style={{ margin: "0 0 8px" }}>Conta Google <b>vinculada</b>{user.login_method === "google" ? " (você entrou por ela agora)" : ""}.</p>
          {company?.password_login !== false && (confirm ? (
            <div className="row">
              <button className="danger" onClick={unlink}>Confirmar: desvincular</button>
              <button onClick={() => setConfirm(false)}>Voltar</button>
            </div>
          ) : <button className="link" style={{ padding: 0 }} onClick={() => setConfirm(true)}>Desvincular a conta Google</button>)}
        </>
      ) : (
        <>
          <p className="muted small" style={{ marginTop: 0 }}>
            Vincule a sua conta Google para entrar com um toque, sem senha. Pode ser uma conta com outro e-mail.
          </p>
          <GoogleButton clientId={config.google_client_id} onCredential={link} text="continue_with" />
        </>
      )}
      {company?.password_login === false && <p className="muted small" style={{ margin: "8px 0 0" }}>Nesta empresa o acesso é só pelo Google.</p>}
    </section>
  );
}

function ChangePassword() {
  const { applyTokens } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next !== again) {
      setMsg({ type: "error", text: "A confirmação não é igual à senha nova" });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const t = await api<Tokens>("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent(""); setNext(""); setAgain("");
      await applyTokens(t); // as outras sessões desta conta caíram; esta continua
      setMsg({ type: "ok", text: "Senha alterada. Os outros aparelhos precisarão entrar de novo." });
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      <label>Senha atual<input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
      <label>Senha nova<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></label>
      <label>Repita a senha nova<input type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} /></label>
      <p className="muted small">Ao menos 10 caracteres, com letras e números; não use seu e-mail nem seu CPF.</p>
      <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Salvando…" : "Trocar senha"}</button>
    </form>
  );
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Códigos de recuperação do Ponto (uso único)\n\n${text}\n`], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "codigos-de-recuperacao.txt";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="alert info" role="status">
      <strong>Guarde estes códigos de recuperação agora.</strong>
      <p className="small" style={{ margin: "4px 0 8px" }}>
        Cada um vale uma vez e só aparece nesta tela. Se você perder o celular, eles são a única forma de entrar sem o RH.
      </p>
      <ul className="plain" style={{ columns: 2, fontFamily: "ui-monospace, monospace" }}>
        {codes.map((c) => <li key={c} style={{ display: "block", padding: "2px 0", border: 0 }}>{c}</li>)}
      </ul>
      <div className="row">
        <button onClick={download}>Baixar (.txt)</button>
        <button onClick={() => navigator.clipboard?.writeText(text)}>Copiar</button>
        <button className="primary" onClick={onDone}>Já guardei</button>
      </div>
    </div>
  );
}

function TwoFactor() {
  const { twoFactor, applyTokens, reload } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [mode, setMode] = useState<"" | "disable" | "regen">("");

  const fail = (e: unknown) => setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });

  async function start() {
    setMsg(null);
    try {
      setSetup(await api<{ secret: string; qr: string }>("/auth/2fa/setup", { method: "POST" }));
    } catch (e) {
      fail(e);
    }
  }

  async function enable(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<Tokens & { recovery_codes: string[] }>("/auth/2fa/enable", { method: "POST", body: { code } });
      setSetup(null); setCode("");
      setCodes(r.recovery_codes); // aparecem uma única vez
      await applyTokens(r);
    } catch (err) {
      fail(err);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    try {
      if (mode === "disable") {
        const t = await api<Tokens>("/auth/2fa/disable", { method: "POST", body: { password, code } });
        await applyTokens(t);
        setMsg({ type: "ok", text: "Verificação em duas etapas desativada." });
      } else {
        const r = await api<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes", { method: "POST", body: { password, code } });
        setCodes(r.recovery_codes);
        await reload();
      }
      setMode(""); setPassword(""); setCode("");
    } catch (err) {
      fail(err);
    }
  }

  return (
    <section className="card">
      <h2 className="section-title">Verificação em duas etapas (2FA)</h2>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      {codes && <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />}

      {twoFactor && !twoFactor.enabled && !setup && (
        <>
          <p className="muted">
            Além da senha, o login pede um código de 6 dígitos de um aplicativo autenticador (Google Authenticator,
            Microsoft Authenticator, Authy…). Protege sua conta mesmo se a senha vazar.
          </p>
          <button className="primary" onClick={start}>Ativar</button>
        </>
      )}

      {setup && (
        <form onSubmit={enable}>
          <p><strong>1.</strong> No aplicativo autenticador, escaneie o QR code (ou digite a chave):</p>
          <div style={{ textAlign: "center" }}>
            <img src={setup.qr} alt="QR code para o aplicativo autenticador" width={200} height={200} style={{ background: "#fff", padding: 8, borderRadius: 8 }} />
            <p className="small" style={{ wordBreak: "break-all", fontFamily: "ui-monospace, monospace" }}>{setup.secret}</p>
          </div>
          <p><strong>2.</strong> Digite o código de 6 dígitos que o aplicativo mostra:</p>
          <label>Código<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" /></label>
          <div className="row"><button className="primary">Confirmar e ativar</button><button type="button" onClick={() => { setSetup(null); setCode(""); }}>Cancelar</button></div>
        </form>
      )}

      {twoFactor?.enabled && (
        <>
          <p className="alert ok" role="status" style={{ marginBottom: 8 }}>Ativa. Códigos de recuperação restantes: <b>{twoFactor.recovery_codes_left}</b> de 8.</p>
          {!mode && (
            <div className="row">
              <button onClick={() => setMode("regen")}>Gerar novos códigos de recuperação</button>
              <button className="danger" onClick={() => setMode("disable")}>Desativar</button>
            </div>
          )}
          {mode && (
            <form onSubmit={confirm}>
              <p className="muted small">Confirme com a sua senha e um código do aplicativo (ou de recuperação).</p>
              <label>Senha<input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
              <label>Código<input required autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></label>
              <div className="row"><button className={mode === "disable" ? "danger" : "primary"}>{mode === "disable" ? "Desativar 2FA" : "Gerar novos códigos"}</button><button type="button" onClick={() => setMode("")}>Cancelar</button></div>
            </form>
          )}
        </>
      )}
    </section>
  );
}
