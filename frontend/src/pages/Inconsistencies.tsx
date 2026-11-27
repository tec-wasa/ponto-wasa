import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { currentMonth, fmtDateTimeMin, fmtDay, fmtMonth, shiftMonth } from "../util";

/** Gestão > Inconsistências: o que a CLT pede atenção no mês (falta, intervalo, 11 h entre jornadas, 7º dia, mais de 2 h
 * extras, ponto britânico). Calculado do espelho; a gestão corrige no Tratamento ou marca como resolvida com uma observação. */

interface Item {
  user_id: number; name: string; job_title: string | null; date: string; kind: string; label: string; legal: string; detail: string;
  resolved: { note: string; by: string | null; at: string } | null;
}
interface Data {
  start: string; end: string; can_resolve: boolean; open: number; resolved: number;
  kinds: { kind: string; label: string; legal: string; open: number }[];
  items: Item[];
}

const QUICK_NOTES = ["Hora extra autorizada", "Corrigido no tratamento", "Combinado com a pessoa", "Situação excepcional"];
const keyOf = (i: Item) => `${i.user_id}|${i.date}|${i.kind}`;

function lastDay(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${month}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
}

function toCsv(items: Item[], tz: string): string {
  const esc = (v: string) => (/[;"\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const head = ["Data", "Colaborador", "Inconsistência", "Detalhe", "Base", "Situação", "Observação", "Resolvida por", "Em"];
  const rows = items.map((i) => [
    i.date.split("-").reverse().join("/"), i.name, i.label, i.detail, i.legal, i.resolved ? "Resolvida" : "Aberta",
    i.resolved?.note ?? "", i.resolved?.by ?? "", i.resolved ? fmtDateTimeMin(i.resolved.at, tz) : "",
  ]);
  return "﻿" + [head, ...rows].map((r) => r.map(esc).join(";")).join("\r\n");
}

export default function Inconsistencies() {
  const { company } = useAuth();
  const tz = company!.timezone;
  const [params, setParams] = useSearchParams();
  const [month, setMonth] = useState(params.get("mes") ?? currentMonth(tz));
  const [showResolved, setShowResolved] = useState(false);
  const [data, setData] = useState<Data | null>(null);
  const [kind, setKind] = useState("");
  const [person, setPerson] = useState<number | "">("");
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api<Data>(`/inconsistencies?start=${month}-01&end=${lastDay(month)}&resolved=${showResolved}`));
    } catch (e) {
      setData(null);
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    } finally {
      setBusy(false);
    }
  }, [month, showResolved]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setParams({ mes: month }, { replace: true }); }, [month, setParams]);

  const people = useMemo(() => {
    const seen = new Map<number, string>();
    for (const i of data?.items ?? []) seen.set(i.user_id, i.name);
    return [...seen].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);
  const byPerson = useMemo(() => (data?.items ?? []).filter((i) => !person || i.user_id === person), [data, person]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const i of byPerson) if (!i.resolved) c[i.kind] = (c[i.kind] ?? 0) + 1;
    return c;
  }, [byPerson]);
  const shown = byPerson.filter((i) => !kind || i.kind === kind);
  const openCount = byPerson.filter((i) => !i.resolved).length;

  async function send(path: string, body: object, okText: string) {
    try {
      await api(path, { method: "POST", body });
      setMsg({ type: "ok", text: okText });
      setOpen(null);
      setNote("");
      await load();
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([toCsv(shown, tz)], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `inconsistencias-${month}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <h1>Inconsistências</h1>
      <p className="muted small" style={{ marginTop: -6 }}>
        O que a CLT pede atenção no mês: faltas, saídas não registradas, intervalo curto, menos de 11 h entre jornadas, 7º dia seguido
        sem folga, mais de 2 h extras e horários idênticos todo dia. Corrija no Tratamento ou marque como resolvida com uma observação.
      </p>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      <div className="grid2 keep" style={{ alignItems: "end" }}>
        <label>Colaborador
          <select value={person} onChange={(e) => setPerson(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Todos</option>
            {people.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <div className="month-nav" style={{ marginBottom: 12 }}>
          <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Mês anterior">‹</button>
          <strong className="month-title" aria-live="polite">{fmtMonth(month)}</strong>
          <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Próximo mês" disabled={month >= currentMonth(tz)}>›</button>
        </div>
      </div>

      {data && (
        <div className="chips-row" role="group" aria-label="Tipo de inconsistência">
          <button className={`fchip${kind === "" ? " on" : ""}`} aria-pressed={kind === ""} onClick={() => setKind("")}>
            Todas <span className="count">{openCount}</span>
          </button>
          {data.kinds.filter((k) => counts[k.kind] || kind === k.kind).map((k) => (
            <button key={k.kind} className={`fchip${kind === k.kind ? " on" : ""}`} aria-pressed={kind === k.kind} title={k.legal}
              onClick={() => setKind(kind === k.kind ? "" : k.kind)}>
              {k.label} <span className="count">{counts[k.kind] ?? 0}</span>
            </button>
          ))}
        </div>
      )}

      <div className="row" style={{ justifyContent: "space-between", margin: "0 0 12px" }}>
        <label className="check" style={{ flex: "0 1 auto", margin: 0 }}>
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
          <span>Mostrar as resolvidas{data && data.resolved > 0 ? ` (${data.resolved})` : ""}</span>
        </label>
        <button onClick={download} disabled={!shown.length} style={{ flex: "0 0 auto" }}>Baixar planilha (CSV)</button>
      </div>

      {busy && !data && <p className="muted" role="status">Calculando o mês…</p>}
      {data && shown.length === 0 && (
        <p className="card muted">{openCount === 0 && !kind ? "Nenhuma inconsistência aberta neste mês." : "Nada com este filtro."}</p>
      )}
      {shown.length > 0 && (
        <section className="card" aria-label="Inconsistências do mês">
          <ul className="plain">
            {shown.map((i) => {
              const k = keyOf(i);
              return (
                <li key={k} className="request" style={i.resolved ? { opacity: 0.75 } : undefined}>
                  <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                    <strong>{i.name}</strong>
                    <span className={`tag ${i.resolved ? "approved" : "pending"}`} style={{ flex: "none" }} title={i.legal}>{i.label}</span>
                  </div>
                  <span><b>{fmtDay(i.date)}</b> · {i.detail}</span>
                  <span className="muted small">{i.legal}</span>
                  {i.resolved && (
                    <span className="muted small">
                      Resolvida{i.resolved.by ? ` por ${i.resolved.by}` : ""} em {fmtDateTimeMin(i.resolved.at, tz)}: “{i.resolved.note}”
                    </span>
                  )}
                  {open === k ? (
                    <div className="request-actions">
                      <div className="quick" role="group" aria-label="Observações comuns">
                        {QUICK_NOTES.map((q) => <button type="button" key={q} className="fchip" onClick={() => setNote(q)}>{q}</button>)}
                      </div>
                      <label>Observação (fica registrada)
                        <input value={note} onChange={(e) => setNote(e.target.value)} autoFocus maxLength={300} />
                      </label>
                      <div className="row">
                        <button className="primary" disabled={note.trim().length < 3}
                          onClick={() => send("/inconsistencies/resolve", { user_id: i.user_id, date: i.date, kind: i.kind, note: note.trim() },
                            "Inconsistência marcada como resolvida.")}>
                          Confirmar
                        </button>
                        <button onClick={() => { setOpen(null); setNote(""); }}>Voltar</button>
                      </div>
                    </div>
                  ) : (
                    <div className="row request-actions" style={{ justifyContent: "flex-start" }}>
                      <Link className="button" style={{ flex: "0 0 auto" }} to={`/gestao/tratamento?user=${i.user_id}&mes=${i.date.slice(0, 7)}&dia=${i.date}`}>Abrir no tratamento</Link>
                      {data?.can_resolve && !i.resolved && (
                        <button style={{ flex: "0 0 auto" }} onClick={() => { setOpen(k); setNote(""); }}>Marcar como resolvida</button>
                      )}
                      {data?.can_resolve && i.resolved && (
                        <button style={{ flex: "0 0 auto" }} onClick={() => send("/inconsistencies/reopen", { user_id: i.user_id, date: i.date, kind: i.kind }, "Inconsistência reaberta.")}>
                          Reabrir
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}
