import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { GoogleButton, useConfig } from "../google";

export default function Login() {
  const { login, loginGoogle } = useAuth();
  const config = useConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [askOtp, setAskOtp] = useState(false); // a senha estava certa e a conta usa 2FA
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email.trim(), password, otp.trim());
    } catch (err) {
      if (err instanceof ApiError && err.code === "otp_required") {
        setAskOtp(true);
      } else {
        setError(err instanceof Error ? err.message : "Falha ao entrar");
        if (err instanceof ApiError && err.code === "otp_invalid") setOtp("");
      }
    } finally {
      setBusy(false);
    }
  }

  async function google(credential: string) {
    setBusy(true);
    setError("");
    try {
      await loginGoogle(credential);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao entrar com o Google");
    } finally {
      setBusy(false);
    }
  }

  const hasGoogle = !!config?.google_client_id;
  const passwordForm = !hasGoogle || showPassword || askOtp;

  return (
    <main style={{ maxWidth: 420, paddingTop: "12vh" }}>
      <h1>Ponto</h1>
      <p className="muted">Entre para registrar e acompanhar sua jornada.</p>
      <section className="card">
        {error && <p className="alert error" role="alert">{error}</p>}
        {hasGoogle && !askOtp && (
          <>
            <GoogleButton clientId={config!.google_client_id!} onCredential={google} />
            <p className="muted small" style={{ textAlign: "center", margin: "10px 0 0" }}>
              Use a conta Google do e-mail que a sua empresa cadastrou.
            </p>
          </>
        )}
        {hasGoogle && !passwordForm && (
          <button className="link" style={{ display: "block", margin: "12px auto 0" }} onClick={() => setShowPassword(true)}>Entrar com e-mail e senha</button>
        )}
        {passwordForm && (
          <form onSubmit={submit} style={hasGoogle && !askOtp ? { marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" } : undefined}>
            <label>
              E-mail
              <input type="email" autoComplete="username" required value={email} disabled={askOtp} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Senha
              <input type="password" autoComplete="current-password" required value={password} disabled={askOtp} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {askOtp && (
              <>
                <p className="alert info" role="status">Sua conta usa verificação em duas etapas.</p>
                <label>
                  Código do aplicativo autenticador
                  <input inputMode="numeric" autoComplete="one-time-code" autoFocus required value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="000000" />
                </label>
                <p className="muted small">Perdeu o celular? Digite um dos seus códigos de recuperação (ex.: abcd-efgh) no lugar do código.</p>
              </>
            )}
            <button className="primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? "Entrando…" : askOtp ? "Confirmar" : "Entrar"}
            </button>
            {askOtp && <button type="button" className="link" onClick={() => { setAskOtp(false); setOtp(""); setPassword(""); }}>Voltar</button>}
          </form>
        )}
      </section>
      <p className="muted small" style={{ textAlign: "center" }}>
        <Link to="/privacidade">Política de privacidade</Link> · <Link to="/termos">Termos de uso</Link>
      </p>
    </main>
  );
}
