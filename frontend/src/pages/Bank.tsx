import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { BankStatement, BankSummary, User } from "../types";
import { fmtMinutes, todayLocal } from "../util";

const sign = (m: number) => (m > 0 ? "+" : "") + fmtMinutes(m);
const cls = (m: number) => (m > 0 ? "pos" : m < 0 ? "neg" : "");
const br = (iso: string) => iso.split("-").reverse().join("/");

function daysAgo(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

export default function Bank() {
  const { user, company, reload } = useAuth();
  const tz = company!.timezone;
  const today = todayLocal(tz);
  const isApprover = !!user && ["manager", "hr", "admin"].includes(user.role);
  const isHr = !!user && ["hr", "admin"].includes(user.role);

  const [people, setPeople] = useState<User[]>([]);
  const [target, setTarget] = useState<number | "">("");
  const [start, setStart] = useState(daysAgo(today, 90));
  const [end, setEnd] = useState(today);
  const [summary, setSummary] = useState<BankSummary | null>(null);
  const [statement, setStatement] = useState<BankStatement | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (isApprover) api<User[]>("/users").then((u) => setPeople(u.filter((p) => p.hour_bank_enabled))).catch(() => undefined);
  }, [isApprover]);

  const load = useCallback(async () => {
    if (user?.tracks_time === false && !target) { setSummary(null); setStatement(null); return; }  // só gere: escolha uma pessoa
    const who = target ? `&user_id=${target}` : "";
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
  }, [target, start, end, user?.tracks_time]);

  useEffect(() => {
    load();
  }, [load]);

  const viewedId = target || user?.id;
  return (
    <>
      <h1>Banco de horas</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      {isApprover && (
        <label>
          Colaborador
          <select value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")}>
            {user?.tracks_time !== false ? <option value="">Eu ({user?.name})</option> : <option value="">Escolha…</option>}
            {people.filter((p) => p.id !== user?.id && p.tracks_time !== false).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      )}

      {summary && !summary.enabled && (
        <p className="card muted">
          {target ? "Este colaborador não usa banco de horas." : "Você não usa banco de horas. O RH pode ativá-lo no seu cadastro."}
        </p>
      )}

      {summary?.enabled && (
        <>
          <section className="card hero" aria-label="Saldo do banco de horas">
            <span className="section-title">Saldo atual</span>
            <div className={`hero-balance ${cls(summary.balance)}`}>{sign(summary.balance)}</div>
            <p className="muted small" style={{ margin: 0 }}>Conta desde {summary.since ? br(summary.since) : "—"}</p>
            <div className="stat-row">
              <div><span className="section-title">Automático</span><b>{sign(summary.automatic ?? 0)}</b></div>
              <div><span className="section-title">Créditos RH</span><b>{fmtMinutes(summary.credits ?? 0)}</b></div>
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
                      {l.description}{l.source === "lancamento" && <span className="tag" style={{ marginLeft: 6 }}>RH</span>}
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

          {isHr && viewedId !== user?.id && (
            <details className="fold">
              <summary>Fazer um lançamento (RH)</summary>
              <EntryForm userId={Number(viewedId)} today={today} onDone={(t) => { setMsg({ type: "ok", text: t }); load(); }} onFail={(t) => setMsg({ type: "error", text: t })} />
            </details>
          )}
        </>
      )}

      {user?.role === "admin" && (
        <details className="fold">
          <summary>Regras do banco de horas (administrador)</summary>
          <Settings onSaved={async () => { await reload(); setMsg({ type: "ok", text: "Configuração salva." }); load(); }} onFail={(t) => setMsg({ type: "error", text: t })} />
        </details>
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

function Settings({ onSaved, onFail }: { onSaved: () => void; onFail: (t: string) => void }) {
  const { company } = useAuth();
  const [limit, setLimit] = useState(company?.bank_max_minutes != null ? String(company.bank_max_minutes / 60) : "");
  const [months, setMonths] = useState(String(company?.bank_expiry_months ?? 6));

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/company", { method: "PATCH", body: { bank_max_minutes: limit === "" ? null : Math.round(Number(limit) * 60), bank_expiry_months: Number(months) } });
      onSaved();
    } catch (err) {
      onFail(err instanceof Error ? err.message : "Erro");
    }
  }

  return (
    <form onSubmit={save}>
      <div className="grid2 keep">
        <label>Limite do saldo (horas; vazio = sem)<input type="number" min="0" step="0.5" value={limit} onChange={(e) => setLimit(e.target.value)} /></label>
        <label>Prazo para compensar (meses)<input type="number" min="1" max="12" value={months} onChange={(e) => setMonths(e.target.value)} /></label>
      </div>
      <p className="muted small">O prazo depende do instrumento adotado (acordo individual ou coletivo); confirme com a assessoria jurídica.</p>
      <button>Salvar</button>
    </form>
  );
}
