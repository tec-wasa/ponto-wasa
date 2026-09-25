import { useState, type FormEvent } from "react";
import { ApiError } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [askOtp, setAskOtp] = useState(false); // a senha estava certa e a conta usa 2FA
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  return (
    <main style={{ maxWidth: 420, paddingTop: "12vh" }}>
      <h1>Ponto</h1>
      <p className="muted">Entre para registrar e acompanhar sua jornada.</p>
      <form className="card" onSubmit={submit}>
        {error && <p className="alert error" role="alert">{error}</p>}
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
    </main>
  );
}
