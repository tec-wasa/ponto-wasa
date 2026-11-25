import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Dashboard } from "../types";
import { fmtMinutes, localToUtcIso } from "../util";

const ORDER = ["sem_marcacao", "incompleto", "presente", "em_intervalo", "aguardando", "saiu", "justificada", "folga"] as const;
const LABEL: Record<string, string> = {
  sem_marcacao: "Sem marcação", incompleto: "Saída não registrada", presente: "Trabalhando",
  em_intervalo: "Em intervalo", aguardando: "Ainda não iniciou", saiu: "Saiu", justificada: "Ausência justificada", folga: "Folga",
};
const DOT: Record<string, string> = {
  presente: "working", em_intervalo: "break", sem_marcacao: "danger", incompleto: "danger", justificada: "working",
};

const initials = (name: string) => {
  const p = name.trim().split(/\s+/);
  return ((p[0]?.[0] ?? "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
};

export default function Team() {
  const { company } = useAuth();
  const tz = company!.timezone;
  const [data, setData] = useState<Dashboard | null>(null);
  const [at, setAt] = useState(""); // vazio = agora; senão "AAAA-MM-DDTHH:mm" (hora local da empresa)
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const q = new URLSearchParams({ bank: "true" });
      if (at) {
        const [d, t] = at.split("T");
        q.set("at", localToUtcIso(d, t, tz));
      }
      setData(await api<Dashboard>(`/dashboard?${q}`));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar o painel");
    }
  }, [at, tz]);

  useEffect(() => {
    load();
    if (at) return;
    const t = setInterval(load, 60_000); // "agora" se atualiza sozinho
    return () => clearInterval(t);
  }, [load, at]);

  const s = data?.summary;
  const people = (data?.people ?? []).filter((p) => !filter || p.state === filter);
  const [d, t] = data ? [data.date.split("-").reverse().join("/"), data.as_of.slice(11)] : ["", ""];
  const attention = s ? s.pending_adjustments + s.late + s.bank_alerts : 0;

  return (
    <>
      <h1 style={{ margin: 0 }}>Painel</h1>
      <p className="muted small" aria-live="polite" style={{ margin: "4px 0 14px" }}>
        {at ? `Situação em ${d} às ${t}` : `Agora, ${t} · atualiza a cada minuto`}
      </p>
      {error && <p className="alert error" role="alert">{error}</p>}

      {s && (
        <>
          <div className="chips-row" role="group" aria-label="Filtrar por situação">
            <button className={`fchip ${filter === "" ? "on" : ""}`} aria-pressed={filter === ""} onClick={() => setFilter("")}>Todos {s.total}</button>
            {ORDER.filter((k) => s[k] > 0).map((k) => (
              <button key={k} className={`fchip ${filter === k ? "on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(filter === k ? "" : k)}>
                <span className={`dot ${DOT[k] ?? ""}`} aria-hidden="true" /> {LABEL[k]} {s[k]}
              </button>
            ))}
          </div>

          {attention > 0 && (
            <div className="attn" aria-label="Pontos de atenção">
              {s.pending_adjustments > 0 && <Link to="/gestao/aprovacoes" className="pill">{s.pending_adjustments} ajuste(s) a aprovar</Link>}
              {s.late > 0 && <span className="pill warn-pill">{s.late} atrasado(s) hoje</span>}
              {s.bank_alerts > 0 && <span className="pill warn-pill">{s.bank_alerts} alerta(s) do banco</span>}
            </div>
          )}
        </>
      )}

      <section className="card" style={{ padding: "4px 16px" }}>
        {data && people.length === 0 && <p className="muted">Ninguém nesta situação.</p>}
        {people.map((p) => (
          <Link key={p.user_id} to={`/gestao/espelhos?user=${p.user_id}`} className="person" aria-label={`${p.name}: ${p.state_label}. Abrir espelho`}>
            <span className="avatar" aria-hidden="true">{initials(p.name)}</span>
            <span className="person-main">
              <strong>{p.name}</strong>
              {p.job_title && <span className="muted small"> · {p.job_title}</span>}
              <span className="muted small person-detail">
                {p.first_entry ? `Entrada ${p.first_entry}` : "Sem entrada hoje"}
                {p.late_minutes > 0 && <b className="neg"> · atraso de {p.late_minutes} min</b>}
                {p.worked_minutes > 0 && ` · ${fmtMinutes(p.worked_minutes)} no dia`}
                {p.no_schedule && <span className="warn"> · sem jornada</span>}
              </span>
              {p.bank_balance !== undefined && (
                <span className="small person-detail">
                  Banco <b className={p.bank_balance >= 0 ? "pos" : "neg"}>{p.bank_balance > 0 ? "+" : ""}{fmtMinutes(p.bank_balance)}</b>
                  {(p.bank_alerts ?? []).map((a) => <span key={a.code} className="warn"> · ⚠ {a.message}</span>)}
                </span>
              )}
            </span>
            <span className="person-state"><span className={`dot ${DOT[p.state] ?? ""}`} aria-hidden="true" />{p.state_label}</span>
          </Link>
        ))}
      </section>

      <details className="fold">
        <summary>Ver a situação em outro momento</summary>
        <label>
          Data e hora
          <input type="datetime-local" value={at} max={new Date().toISOString().slice(0, 16)} onChange={(e) => setAt(e.target.value)} />
        </label>
        {at && <button className="link" onClick={() => setAt("")}>Voltar para agora</button>}
      </details>
    </>
  );
}
