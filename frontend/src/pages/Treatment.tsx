import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { User } from "../types";
import { KIND_LABEL, currentMonth, fmtMinutes, fmtMonth, fmtTime, localToUtcIso, shiftMonth, todayLocal } from "../util";

/** Gestão > Tratamento: o mês de uma pessoa, dia a dia, para a gestão corrigir o ponto por conta própria.
 * Nada apaga a marcação original: incluir e desconsiderar viram tratamentos aprovados (AEJ), com motivo, e podem ser desfeitos. */

interface Mark {
  type: "original" | "inclusao"; punch_id?: number; nsr?: number; adjustment_id: number | null; at: string; kind: string; label: string;
  origin?: string; offline?: boolean; voided?: boolean; note: string | null; by: string | null;
}
interface Day {
  date: string; expected: number; worked: number; balance: number; status: string; warnings: string[]; justification: string | null;
  marks: Mark[]; pending: { adjustment_id: number; kind: string; at: string; label: string; reason: string }[];
  absences: { absence_id: number; label: string; status: string; minutes: number | null }[];
}
interface Data {
  user: { id: number; name: string; job_title: string | null }; month: string; closed: boolean; can_treat: boolean; can_justify: boolean;
  totals: { worked_minutes: number; expected_minutes: number; balance_minutes: number; absences: number; justified_days: number; incomplete_days: number };
  days: Day[];
}

const STATUS: Record<string, string> = {
  ok: "Regular", folga: "Folga", falta: "Falta", incompleto: "Incompleto", hoje: "Hoje", futuro: "—",
  anterior: "Antes da admissão", justificada: "Justificada", feriado: "Feriado",
};
const ORDER = ["entrada", "inicio_intervalo", "fim_intervalo", "saida"];
const INCLUDE_REASONS = ["Esqueceu de bater", "Trabalho externo", "Falha no aparelho", "Sem internet no momento"];
const VOID_REASONS = ["Batida duplicada", "Batida por engano", "Batida fora do horário real"];
const JUSTIFY_KINDS: [string, string][] = [["abono", "Abono"], ["atestado_medico", "Atestado médico"], ["ferias", "Férias"],
  ["licenca", "Licença"], ["afastamento_inss", "Afastamento INSS"]];
const attention = (d: Day) => d.status === "falta" || d.status === "incompleto" || d.warnings.length > 0 || d.pending.length > 0;
const sign = (m: number) => (m > 0 ? "+" : "") + fmtMinutes(m);

function dayParts(date: string) {
  const d = new Date(`${date}T12:00:00Z`);
  return { num: String(d.getUTCDate()).padStart(2, "0"), week: d.toLocaleDateString("pt-BR", { weekday: "short", timeZone: "UTC" }).replace(".", "") };
}

export default function Treatment() {
  const { user, company } = useAuth();
  const tz = company!.timezone;
  const [params, setParams] = useSearchParams();
  const [people, setPeople] = useState<User[]>([]);
  const [target, setTarget] = useState<number | "">(Number(params.get("user")) || "");
  const [month, setMonth] = useState(params.get("mes") ?? currentMonth(tz));
  const [data, setData] = useState<Data | null>(null);
  const [view, setView] = useState<"atencao" | "uteis" | "todos">("uteis");
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    api<User[]>("/users").then((u) => setPeople(u.filter((p) => p.id !== user?.id && p.active && p.tracks_time !== false))).catch(() => undefined);
  }, [user?.id]);

  const load = useCallback(async () => {
    if (!target) { setData(null); return; }
    try {
      setData(await api<Data>(`/treatment?month=${month}&user_id=${target}`));
    } catch (e) {
      setData(null);
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [target, month]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setParams(target ? { user: String(target), mes: month } : {}, { replace: true }); }, [target, month, setParams]);

  const shown = useMemo(() => {
    const days = data?.days ?? [];
    if (view === "atencao") return days.filter(attention);
    if (view === "uteis") return days.filter((d) => !["folga", "feriado", "futuro", "anterior"].includes(d.status) || d.marks.length > 0);
    return days;
  }, [data, view]);

  async function act(path: string, body: object | undefined, okText: string) {
    try {
      await api(path, { method: "POST", body });
      setMsg({ type: "ok", text: okText });
      await load();
      return true;
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
      return false;
    }
  }

  const editable = !!data && data.can_treat && !data.closed;
  const t = data?.totals;
  const pendingDays = (data?.days ?? []).filter(attention).length;

  return (
    <>
      <h1>Tratamento do ponto</h1>
      <p className="muted small" style={{ marginTop: -6 }}>
        Corrija o mês de cada pessoa: inclua marcações esquecidas, desconsidere as erradas e justifique faltas. A marcação original nunca é
        apagada; cada correção fica com o motivo, aparece no espelho da pessoa e entra no AEJ.
      </p>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      <div className="grid2 keep" style={{ alignItems: "end" }}>
        <label>Colaborador
          <select value={target} onChange={(e) => { setTarget(e.target.value ? Number(e.target.value) : ""); setOpen(null); setMsg(null); }}>
            <option value="">Escolha…</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="month-nav" style={{ marginBottom: 12 }}>
          <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Mês anterior">‹</button>
          <strong className="month-title" aria-live="polite">{fmtMonth(month)}</strong>
          <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Próximo mês" disabled={month >= currentMonth(tz)}>›</button>
        </div>
      </div>

      {!target && <p className="card muted">Escolha uma pessoa para ver o mês dela.</p>}
      {data?.closed && <p className="alert info">Este mês está fechado. Para corrigir, reabra em Empresa &gt; Fechamento.</p>}
      {data && !data.can_treat && !data.closed && <p className="alert info">Você acompanha esta pessoa, mas não trata o ponto dela.</p>}

      {t && (
        <section className="card summary" aria-label="Resumo do mês">
          <div className="summary-main">
            <div><span className="section-title">Trabalhadas</span><b>{fmtMinutes(t.worked_minutes)}</b></div>
            <div><span className="section-title">Previstas</span><b>{fmtMinutes(t.expected_minutes)}</b></div>
            <div><span className="section-title">Saldo</span><b className={t.balance_minutes >= 0 ? "pos" : "neg"}>{sign(t.balance_minutes)}</b></div>
          </div>
          <p className="summary-line muted small">
            Faltas <b>{t.absences}</b> · Justificados <b>{t.justified_days}</b> · Incompletos <b>{t.incomplete_days}</b>
            {" · "}<Link to={`/gestao/espelhos?user=${data!.user.id}`}>Ver o espelho</Link>
          </p>
        </section>
      )}

      {data && (
        <>
          <div className="seg" role="group" aria-label="Quais dias mostrar">
            <button className={view === "atencao" ? "on" : ""} aria-pressed={view === "atencao"} onClick={() => setView("atencao")}>
              Pendências{pendingDays > 0 && <span className="count">{pendingDays}</span>}
            </button>
            <button className={view === "uteis" ? "on" : ""} aria-pressed={view === "uteis"} onClick={() => setView("uteis")}>Dias úteis</button>
            <button className={view === "todos" ? "on" : ""} aria-pressed={view === "todos"} onClick={() => setView("todos")}>Todos</button>
          </div>
          <section className="card" style={{ padding: "4px 16px" }}>
            {shown.length === 0 && <p className="muted">{view === "atencao" ? "Nenhuma pendência neste mês." : "Nenhum dia para mostrar."}</p>}
            {shown.map((d) => (
              <DayRow key={d.date} d={d} tz={tz} open={open === d.date} onToggle={(o) => setOpen(o ? d.date : null)}
                editable={editable} canJustify={!!data.can_justify && !data.closed} userId={data.user.id} act={act} />
            ))}
          </section>
        </>
      )}
    </>
  );
}

function DayRow({ d, tz, open, onToggle, editable, canJustify, userId, act }: {
  d: Day; tz: string; open: boolean; onToggle: (o: boolean) => void; editable: boolean; canJustify: boolean; userId: number;
  act: (path: string, body: object | undefined, ok: string) => Promise<boolean>;
}) {
  const { num, week } = dayParts(d.date);
  const [voiding, setVoiding] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"" | "incluir" | "justificar">("");
  const future = d.status === "futuro" || d.date > todayLocal(tz);
  const valid = d.marks.filter((m) => !m.voided);
  const suggested = ORDER[Math.min(valid.length, 3)];

  async function voidMark(m: Mark) {
    if (await act("/adjustments", { kind: "desconsiderar", user_id: userId, target_punch_id: m.punch_id, reason: reason.trim() },
      `Marcação de ${fmtTime(m.at, tz)} desconsiderada.`)) { setVoiding(null); setReason(""); }
  }

  return (
    <details className="day-row" open={open} onToggle={(e) => onToggle(e.currentTarget.open)}>
      <summary>
        <span className="day-date"><b>{num}</b><small>{week}</small></span>
        <span className="day-main">
          <span>
            <span className={`tag ${d.status}`}>{STATUS[d.status] ?? d.status}</span>
            {d.justification && <span className="muted small"> {d.justification}</span>}
            {d.pending.length > 0 && <span className="tag pending" style={{ marginLeft: 4 }}>{d.pending.length} pedido(s)</span>}
          </span>
          <span className="muted small day-times">
            {d.marks.length ? d.marks.map((m, i) => (
              <span key={i} style={m.voided ? { textDecoration: "line-through", opacity: 0.6 } : undefined}>
                {i > 0 && " · "}{fmtTime(m.at, tz)}{m.type === "inclusao" ? "*" : ""}
              </span>
            )) : "Sem marcações"}
          </span>
        </span>
        <span className="day-num">
          {d.worked ? fmtMinutes(d.worked) : ""}
          {d.balance ? <small className={d.balance > 0 ? "pos" : "neg"}>{sign(d.balance)}</small> : null}
        </span>
      </summary>
      <div className="day-body">
        {d.marks.length > 0 && (
          <ul className="plain">
            {d.marks.map((m, i) => (
              <li key={i} style={{ flexWrap: "wrap", alignItems: "flex-start" }}>
                <span style={m.voided ? { textDecoration: "line-through", opacity: 0.7 } : undefined}>
                  <b className="when">{fmtTime(m.at, tz)}</b> {m.label || KIND_LABEL[m.kind] || m.kind}
                  <span className="muted small">
                    {m.type === "original" ? ` · ${m.origin}${m.offline ? " (sem internet)" : ""} · NSR ${m.nsr}` : " · incluída"}
                  </span>
                </span>
                {editable && m.type === "original" && !m.voided && voiding !== m.punch_id && (
                  <button className="link" style={{ minHeight: 32 }} onClick={() => { setVoiding(m.punch_id!); setReason(""); setMode(""); }}>Desconsiderar</button>
                )}
                {editable && (m.voided || m.type === "inclusao") && m.adjustment_id && (
                  <button className="link" style={{ minHeight: 32 }}
                    onClick={() => act(`/adjustments/${m.adjustment_id}/revoke`, undefined, m.type === "inclusao" ? "Inclusão desfeita." : "A marcação voltou a valer.")}>
                    Desfazer
                  </button>
                )}
                {(m.voided || m.type === "inclusao") && m.note && (
                  <span className="muted small" style={{ flexBasis: "100%" }}>
                    {m.voided ? "Desconsiderada" : "Incluída"}{m.by ? ` por ${m.by}` : ""}: “{m.note}”
                  </span>
                )}
                {voiding === m.punch_id && (
                  <div style={{ flexBasis: "100%" }}>
                    <div className="quick" role="group" aria-label="Motivos comuns">
                      {VOID_REASONS.map((r) => <button type="button" key={r} className="fchip" onClick={() => setReason(r)}>{r}</button>)}
                    </div>
                    <label>Motivo<input value={reason} onChange={(e) => setReason(e.target.value)} autoFocus /></label>
                    <div className="row">
                      <button className="danger" disabled={reason.trim().length < 5} onClick={() => voidMark(m)}>Desconsiderar</button>
                      <button onClick={() => setVoiding(null)}>Voltar</button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {d.warnings.map((w) => <p className="warn small" key={w}>⚠ {w}</p>)}
        {d.absences.map((a) => (
          <p className="small" key={a.absence_id} style={{ margin: "4px 0" }}>
            <span className={`tag ${a.status}`}>{a.status === "pending" ? "Pedido" : "Ausência"}</span> {a.label}{a.minutes ? ` (${fmtMinutes(a.minutes)})` : ""}
          </p>
        ))}
        {d.pending.length > 0 && (
          <p className="alert info small" style={{ margin: "6px 0" }}>
            {d.pending.map((p) => `${p.kind === "incluir" ? "Pede inclusão" : "Pede desconsiderar"} de ${p.label.toLowerCase()} às ${fmtTime(p.at, tz)}: “${p.reason}”`).join(" · ")}
            {" "}<Link to="/gestao/aprovacoes">Decidir em Aprovações</Link>
          </p>
        )}

        {!future && (editable || canJustify) && (
          <div className="row" style={{ marginTop: 8 }}>
            {editable && <button className={mode === "incluir" ? "primary" : ""} onClick={() => { setMode(mode === "incluir" ? "" : "incluir"); setVoiding(null); }}>Incluir marcação</button>}
            {canJustify && <button className={mode === "justificar" ? "primary" : ""} onClick={() => { setMode(mode === "justificar" ? "" : "justificar"); setVoiding(null); }}>Justificar o dia</button>}
          </div>
        )}
        {mode === "incluir" && <IncludeForm date={d.date} tz={tz} suggested={suggested} userId={userId} act={act} onDone={() => setMode("")} />}
        {mode === "justificar" && <JustifyForm date={d.date} userId={userId} act={act} onDone={() => setMode("")} />}
      </div>
    </details>
  );
}

function IncludeForm({ date, tz, suggested, userId, act, onDone }: {
  date: string; tz: string; suggested: string; userId: number; act: (p: string, b: object | undefined, ok: string) => Promise<boolean>; onDone: () => void;
}) {
  const [kind, setKind] = useState(suggested);
  const [time, setTime] = useState("");
  const [reason, setReason] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act("/adjustments", { kind: "incluir", user_id: userId, requested_at: localToUtcIso(date, time, tz), punch_kind: kind, reason: reason.trim() },
      `${KIND_LABEL[kind]} às ${time} incluída.`);
    if (ok) onDone();
  }

  return (
    <form className="card" style={{ marginTop: 8 }} onSubmit={submit} aria-label="Incluir marcação">
      <div className="grid2 keep">
        <label>Marcação
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {ORDER.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
        </label>
        <label>Hora<input type="time" required value={time} onChange={(e) => setTime(e.target.value)} /></label>
      </div>
      <div className="quick" role="group" aria-label="Motivos comuns">
        {INCLUDE_REASONS.map((r) => <button type="button" key={r} className="fchip" onClick={() => setReason(r)}>{r}</button>)}
      </div>
      <label>Motivo<input required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <div className="row"><button className="primary">Incluir</button><button type="button" onClick={onDone}>Cancelar</button></div>
    </form>
  );
}

function JustifyForm({ date, userId, act, onDone }: {
  date: string; userId: number; act: (p: string, b: object | undefined, ok: string) => Promise<boolean>; onDone: () => void;
}) {
  const [kind, setKind] = useState("abono");
  const [partial, setPartial] = useState(false);
  const [hours, setHours] = useState("1");
  const [reason, setReason] = useState("");
  const canPartial = kind === "abono" || kind === "atestado_medico";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act("/absences", {
      kind, user_id: userId, start_date: date, end_date: date, reason: reason.trim(),
      minutes: partial && canPartial ? Math.round(Number(hours) * 60) : null,
    }, "Dia justificado.");
    if (ok) onDone();
  }

  return (
    <form className="card" style={{ marginTop: 8 }} onSubmit={submit} aria-label="Justificar o dia">
      <label>Tipo
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {JUSTIFY_KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      {canPartial && (
        <label className="check">
          <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} />
          <span>Só parte do dia</span>
        </label>
      )}
      {partial && canPartial && <label>Horas justificadas<input type="number" min="0.25" max="12" step="0.25" value={hours} onChange={(e) => setHours(e.target.value)} /></label>}
      <label>Motivo<input required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Sem diagnóstico nem CID" /></label>
      <p className="muted small">Para vários dias seguidos (férias, licença), use Gestão &gt; Ausências.</p>
      <div className="row"><button className="primary">Justificar</button><button type="button" onClick={onDone}>Cancelar</button></div>
    </form>
  );
}
