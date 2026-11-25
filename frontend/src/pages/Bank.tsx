import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { BankAlert, BankStatement, BankSummary } from "../types";
import { fmtMinutes, todayLocal } from "../util";

const sign = (m: number) => (m > 0 ? "+" : "") + fmtMinutes(m);
const cls = (m: number) => (m > 0 ? "pos" : m < 0 ? "neg" : "");
const br = (iso: string) => iso.split("-").reverse().join("/");

function daysAgo(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Meu ponto > Banco de horas: o saldo e o extrato da própria pessoa. */
export default function MyBank() {
  return (
    <>
      <h1>Banco de horas</h1>
      <BankView />
    </>
  );
}

type TeamRow = { user_id: number; name: string; balance: number; limit_minutes: number | null; at_risk_minutes: number; alerts: BankAlert[] };

/** Gestão > Banco de horas: saldos de quem usa banco de horas (equipe ou empresa), extrato de cada um e lançamentos do RH. */
export function TeamBank() {
  const { can } = useAuth();
  const [rows, setRows] = useState<TeamRow[] | null>(null);
  const [picked, setPicked] = useState<TeamRow | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<TeamRow[]>("/hour-bank/team").then(setRows).catch((e) => setError(e instanceof Error ? e.message : "Erro")), []);
  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <h1>Banco de horas</h1>
      {error && <p className="alert error" role="alert">{error}</p>}
      {rows && rows.length === 0 && (
        <p className="card muted">Ninguém usa banco de horas. Ele é ativado no cadastro de cada pessoa, em Cadastros &gt; Pessoas.</p>
      )}
      {rows && rows.length > 0 && (
        <section className="card" style={{ padding: "4px 16px" }} aria-label="Saldos">
          <ul className="plain">
            {rows.map((r) => (
              <li key={r.user_id}>
                <button className="row-btn" style={{ display: "flex", justifyContent: "space-between", width: "100%" }}
                  aria-pressed={picked?.user_id === r.user_id} onClick={() => setPicked(picked?.user_id === r.user_id ? null : r)}>
                  <span>{r.name}{r.alerts.length > 0 && <span className="warn small"> · ⚠ {r.alerts.map((a) => a.message).join("; ")}</span>}</span>
                  <b className={cls(r.balance)}>{sign(r.balance)}</b>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {picked && (
        <>
          <h2 className="section-title" style={{ marginTop: 20 }}>{picked.name}</h2>
          <BankView userId={picked.user_id} entries={can("hourbank.entries")} onChange={load} />
        </>
      )}
    </>
  );
}

function BankView({ userId, entries, onChange }: { userId?: number; entries?: boolean; onChange?: () => void }) {
  const { company } = useAuth();
  const tz = company!.timezone;
  const today = todayLocal(tz);
  const [start, setStart] = useState(daysAgo(today, 90));
  const [end, setEnd] = useState(today);
  const [summary, setSummary] = useState<BankSummary | null>(null);
  const [statement, setStatement] = useState<BankStatement | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const who = userId ? `&user_id=${userId}` : "";
    try {
      const [s, st] = await Promise.all([
        api<BankSummary>(`/hour-bank?${who.slice(1)}`),
        api<BankStatement>(`/hour-bank/statement?start=${start}&end=${end}${who}`),
      ]);
      setSummary(s);
      setStatement(st);
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [userId, start, end]);
  useEffect(() => { void load(); }, [load]);

  return (
    <>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      {summary && !summary.enabled && (
        <p className="card muted">{userId ? "Esta pessoa não usa banco de horas." : "Você não usa banco de horas: as horas a mais ou a menos aparecem só no seu espelho."}</p>
      )}
      {summary?.enabled && (
        <>
          <section className="card hero" aria-label="Saldo do banco de horas">
            <span className="section-title">Saldo atual</span>
            <div className={`hero-balance ${cls(summary.balance)}`}>{sign(summary.balance)}</div>
            <p className="muted small" style={{ margin: 0 }}>Conta desde {summary.since ? br(summary.since) : "—"}</p>
            <div className="stat-row">
              <div><span className="section-title">Automático</span><b>{sign(summary.automatic ?? 0)}</b></div>
              <div><span className="section-title">Créditos</span><b>{fmtMinutes(summary.credits ?? 0)}</b></div>
              <div><span className="section-title">Compensado</span><b>{fmtMinutes(summary.compensations ?? 0)}</b></div>
            </div>
          </section>

          {summary.alerts.map((a) => <p key={a.code} className="alert error" role="alert">⚠ {a.message}</p>)}

          <section className="card" aria-labelledby="h-extrato">
            <h2 id="h-extrato" className="section-title">Extrato</h2>
            <div className="grid2 keep">
              <label>De<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
              <label>Até<input type="date" value={end} min={start} max={today} onChange={(e) => setEnd(e.target.value)} /></label>
            </div>
            {statement && (
              <ul className="ledger">
                <li className="muted"><span>Saldo anterior</span><b>{sign(statement.opening)}</b></li>
                {statement.lines.map((l, i) => (
                  <li key={i}>
                    <span>
                      <span className="muted small">{br(l.date)}</span><br />
                      {l.description}{l.source === "lancamento" && <span className="tag" style={{ marginLeft: 6 }}>Lançamento</span>}
                    </span>
                    <span className="ledger-num">
                      <b className={cls(l.minutes)}>{sign(l.minutes)}</b>
                      <small className="muted">saldo {sign(l.balance)}</small>
                    </span>
                  </li>
                ))}
                {statement.lines.length === 0 && <li className="muted"><span>Sem movimentos no período.</span></li>}
              </ul>
            )}
          </section>

          <details className="fold">
            <summary>Como funciona</summary>
            <p className="muted small">
              Faltas de dia inteiro não descontam do banco automaticamente.
              {summary.limit_minutes != null && ` Limite do saldo: ${fmtMinutes(summary.limit_minutes)}.`}
              {" "}Prazo para compensar: {summary.expiry_months} meses.
            </p>
          </details>

          {entries && userId && (
            <details className="fold">
              <summary>Fazer um lançamento</summary>
              <EntryForm userId={userId} today={today} onDone={(t) => { setMsg({ type: "ok", text: t }); void load(); onChange?.(); }}
                onFail={(t) => setMsg({ type: "error", text: t })} />
            </details>
          )}
        </>
      )}
    </>
  );
}

function EntryForm({ userId, today, onDone, onFail }: { userId: number; today: string; onDone: (t: string) => void; onFail: (t: string) => void }) {
  const [kind, setKind] = useState("compensacao");
  const [hours, setHours] = useState("1");
  const [mins, setMins] = useState("0");
  const [date, setDate] = useState(today);
  const [reason, setReason] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/hour-bank/entries", {
        method: "POST",
        body: { user_id: userId, kind, minutes: Number(hours) * 60 + Number(mins), entry_date: date, reason },
      });
      setReason("");
      onDone("Lançamento registrado. Ele não pode ser editado; para corrigir, faça o lançamento contrário.");
    } catch (err) {
      onFail(err instanceof Error ? err.message : "Erro");
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="seg" role="group" aria-label="Tipo de lançamento">
        <button type="button" className={kind === "compensacao" ? "on" : ""} aria-pressed={kind === "compensacao"} onClick={() => setKind("compensacao")}>Compensação (−)</button>
        <button type="button" className={kind === "credito" ? "on" : ""} aria-pressed={kind === "credito"} onClick={() => setKind("credito")}>Crédito (+)</button>
      </div>
      <div className="grid2 keep">
        <label>Horas<input type="number" min="0" max="24" value={hours} onChange={(e) => setHours(e.target.value)} /></label>
        <label>Minutos<input type="number" min="0" max="59" value={mins} onChange={(e) => setMins(e.target.value)} /></label>
      </div>
      <label>Data<input type="date" required value={date} max={today} onChange={(e) => setDate(e.target.value)} /></label>
      <label>Motivo<textarea required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: folga compensatória de 12/08" /></label>
      <button className="primary" style={{ width: "100%" }}>Lançar</button>
    </form>
  );
}
