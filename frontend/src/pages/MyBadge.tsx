import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { api } from "../api";

interface Badge { employee_code: string; has_pin: boolean; pin_required: boolean }
interface Qr { qr: string; expires_in: number; image: string }

/** QR rotativo em tela cheia: muda a cada 30 s e não vale como foto de tela. */
function BadgeScreen({ onClose }: { onClose: () => void }) {
  const [qr, setQr] = useState<Qr | null>(null);
  const [left, setLeft] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const r = await api<Qr>("/auth/badge-qr");
        if (!alive) return;
        setQr(r); setLeft(r.expires_in); setErr("");
        timer = setTimeout(load, Math.max(1, r.expires_in - 1) * 1000);
      } catch (e) {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : "Erro");
        timer = setTimeout(load, 5000);
      }
    };
    void load();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="badge-screen" role="dialog" aria-modal="true" aria-label="Meu crachá">
      <p className="badge-title">Aponte para a câmera da Central</p>
      {qr ? <img src={qr.image} alt="QR do meu crachá" className="badge-qr" /> : <div className="badge-qr" />}
      <p className="badge-sub">{err || `Muda em ${left} s`}</p>
      <p className="badge-hint">Aumente o brilho da tela. Este QR é pessoal e vale só por alguns segundos.</p>
      <button className="primary" onClick={onClose}>Fechar</button>
    </div>
  );
}

/** Minha conta: código interno, PIN e QR do crachá para a Central do Ponto. */
export default function MyBadge() {
  const { user } = useAuth();
  const viaGoogle = user?.login_method === "google"; // quem entrou pelo Google não tem senha do app para confirmar
  const [badge, setBadge] = useState<Badge | null>(null);
  const [show, setShow] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ password: "", pin: "", again: "" });
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api<Badge>("/auth/badge").then(setBadge).catch(() => undefined);
  useEffect(() => { void load(); }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (form.pin !== form.again) return setMsg({ type: "error", text: "A confirmação não é igual ao PIN" });
    setBusy(true); setMsg(null);
    try {
      await api("/auth/pin", { method: "POST", body: { password: viaGoogle ? undefined : form.password, pin: form.pin } });
      setForm({ password: "", pin: "", again: "" });
      setOpen(false);
      setMsg({ type: "ok", text: "PIN salvo." });
      await load();
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    } finally {
      setBusy(false);
    }
  }

  if (!badge) return null;
  return (
    <section className="card">
      <h2 className="section-title">Central do Ponto</h2>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      <dl className="receipt">
        <dt>Código interno</dt>
        <dd><code>{show ? badge.employee_code : "••••••"}</code> <button type="button" className="link" onClick={() => setShow(!show)}>{show ? "Ocultar" : "Mostrar"}</button></dd>
        <dt>PIN</dt>
        <dd>{badge.has_pin ? "Definido" : "Não definido"}{badge.pin_required && !badge.has_pin ? " (a empresa exige)" : ""}</dd>
      </dl>
      <p className="muted small">
        Na Central, informe o código (ou o CPF) e, se pedido, o PIN. Trate o código como uma senha: com ele a Central identifica você.
      </p>
      <div className="row">
        <button className="primary" onClick={() => setQrOpen(true)}>Meu crachá (QR)</button>
        <button onClick={() => setOpen(!open)}>{badge.has_pin ? "Trocar o PIN" : "Definir PIN"}</button>
      </div>
      {open && (
        <form onSubmit={save} style={{ marginTop: 12 }}>
          <label>PIN (4 a 6 dígitos)<input type="password" inputMode="numeric" pattern="\d{4,6}" minLength={4} maxLength={6} required autoComplete="off" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value })} /></label>
          <label>Repita o PIN<input type="password" inputMode="numeric" pattern="\d{4,6}" minLength={4} maxLength={6} required autoComplete="off" value={form.again} onChange={(e) => setForm({ ...form, again: e.target.value })} /></label>
          {viaGoogle
            ? <p className="muted small">Você entrou com o Google: por segurança, a troca do PIN só vale nos primeiros 15 minutos depois de entrar.</p>
            : <label>Sua senha atual<input type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>}
          <p className="muted small">Sem sequências óbvias (1234, 0000). Pedimos a senha para que quem pegar seu celular aberto não troque o PIN.</p>
          <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Salvando…" : "Salvar PIN"}</button>
        </form>
      )}
      {qrOpen && <BadgeScreen onClose={() => setQrOpen(false)} />}
    </section>
  );

}
