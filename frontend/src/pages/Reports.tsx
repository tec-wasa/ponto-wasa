import { useState } from "react";
import { download } from "../api";
import { useAuth } from "../auth";
import { currentMonth, shiftMonth, todayLocal } from "../util";

export default function Reports() {
  const { company, user } = useAuth();
  const [origin, setOrigin] = useState("all");
  const tz = company!.timezone;
  const today = todayLocal(tz);
  const [month, setMonth] = useState(() => shiftMonth(currentMonth(tz), -1)); // o fechamento costuma ser do mês que acabou
  const [start, setStart] = useState(() => `${currentMonth(tz)}-01`);
  const [end, setEnd] = useState(today);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState("");

  async function get(key: string, path: string, name: string) {
    setBusy(key);
    setError("");
    setDone("");
    try {
      await download(path, name);
      setDone(`${name} gerado. Confira a pasta de downloads.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar o relatório");
    } finally {
      setBusy("");
    }
  }

  const buttons = (key: string, path: string, name: string, disabled = false) => (
    <div className="row">
      {(["pdf", "csv"] as const).map((f) => (
        <button key={f} className={f === "pdf" ? "primary" : ""} disabled={!!busy || disabled}
          onClick={() => get(key + f, `${path}${path.includes("?") ? "&" : "?"}format=${f}`, `${name}.${f}`)}>
          {busy === key + f ? "Gerando…" : f === "pdf" ? "Baixar PDF" : "Baixar planilha (CSV)"}
        </button>
      ))}
    </div>
  );

  const q = new URLSearchParams({ start, end });
  if (status) q.set("status", status);

  return (
    <>
      <h1>Relatórios</h1>
      <p className="muted small" style={{ marginTop: -4 }}>
        O gestor vê a própria equipe; RH, administrador e auditor veem a empresa. Cada emissão fica na auditoria.
        O documento oficial de cada pessoa continua sendo o Espelho de Ponto.
      </p>
      {error && <p className="alert error" role="alert">{error}</p>}
      {done && <p className="alert ok" role="status">{done}</p>}

      <section className="card" aria-labelledby="r-mensal">
        <h2 id="r-mensal" className="section-title">Fechamento mensal</h2>
        <p className="muted small">Horas trabalhadas, saldo, faltas, dias justificados e banco de horas de cada pessoa.</p>
        <label>Mês<input type="month" value={month} max={currentMonth(tz)} onChange={(e) => setMonth(e.target.value)} /></label>
        {buttons("m", `/reports/monthly?month=${month}`, `fechamento-${month}`, !month)}
      </section>

      <section className="card" aria-labelledby="r-banco">
        <h2 id="r-banco" className="section-title">Banco de horas</h2>
        <p className="muted small">Posição de hoje de quem usa banco de horas: saldo, limite e horas em risco de vencer.</p>
        {buttons("b", "/reports/hour-bank", `banco-de-horas-${today}`)}
      </section>

      <section className="card" aria-labelledby="r-ausencias">
        <h2 id="r-ausencias" className="section-title">Ausências justificadas</h2>
        <p className="muted small">Atestados, abonos, férias, licenças e afastamentos. Motivos de saúde só aparecem para o RH.</p>
        <div className="grid2 keep">
          <label>De<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Até<input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
        <label>Situação
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todas</option><option value="approved">Aprovadas</option><option value="pending">Pendentes</option>
            <option value="rejected">Rejeitadas</option><option value="cancelled">Canceladas</option>
          </select>
        </label>
        {buttons("a", `/reports/absences?${q}`, `ausencias-${start}-${end}`, !start || !end)}
      </section>

      <section className="card" aria-labelledby="r-batidas">
        <h2 id="r-batidas" className="section-title">Batidas por origem</h2>
        <p className="muted small">Cada marcação (NSR) do período, com a origem (aplicativo ou Central) e a distância ao posto.</p>
        <div className="grid2 keep">
          <label>De<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Até<input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
        <label>Origem
          <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <option value="all">Todas</option><option value="app">Só o aplicativo</option><option value="central">Só a Central</option>
          </select>
        </label>
        {buttons("p", `/reports/punches?${new URLSearchParams({ start, end, origin })}`, `batidas-${start}-${end}`, !start || !end)}
      </section>

      {user && ["hr", "admin", "auditor"].includes(user.role) && (
        <section className="card" aria-labelledby="r-diverg">
          <h2 id="r-diverg" className="section-title">Divergências da Central</h2>
          <p className="muted small">Batidas fora do posto ou sem localização, falhas de identificação e aparelhos sem sinal. Não bloqueiam a batida: servem para conferência.</p>
          {buttons("d", `/reports/kiosk-divergences?${new URLSearchParams({ start, end })}`, `divergencias-central-${start}-${end}`, !start || !end)}
        </section>
      )}
    </>
  );
}
