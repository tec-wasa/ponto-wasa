import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, download } from "../api";
import { useAuth } from "../auth";
import type { AuditRow, Closing, Schedule } from "../types";
import Kiosks from "./Kiosks";
import People from "./People";
import Settings from "./Settings";
import { currentMonth, fmtDateTime, fmtMinutes, shiftMonth, todayLocal } from "../util";

const DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const ACTION_LABEL: Record<string, string> = {
  create: "Criou", update: "Alterou", punch: "Marcação", approve: "Aprovou", reject: "Rejeitou", cancel: "Cancelou", export: "Exportou",
  close: "Fechou", reopen: "Reabriu", login: "Login", disable: "Desativou", enable: "Ativou",
  reset_password: "Gerou nova senha", reset_2fa: "Zerou o 2FA", pin_reset: "Zerou o PIN", pin_set: "Definiu o PIN",
  badge_print: "Imprimiu crachá", badge_regenerate: "Regenerou o crachá", repair: "Refez o pareamento", revoke: "Revogou",
  kiosk_paired: "Central pareada", kiosk_punch: "Batida na Central", kiosk_identify: "Identificou na Central", consent_photo: "Autorizou a foto", kiosk_offline_rejected: "Batida sem internet recusada",
};

function useNotice() {
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const fail = (e: unknown) => setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
  const ok = (text: string) => setMsg({ type: "ok", text });
  const el = msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>;
  return { ok, fail, el };
}

function Tabs<T extends string>({ label, tabs, tab, onTab }: { label: string; tabs: [T, string][]; tab: T; onTab: (t: T) => void }) {
  if (tabs.length < 2) return null;
  return (
    <div className="seg scroll-x" role="tablist" aria-label={label} style={{ margin: "14px 0" }}>
      {tabs.map(([id, text]) => (
        <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => onTab(id)}>{text}</button>
      ))}
    </div>
  );
}

/** Gestão > Cadastros: pessoas, jornadas e centrais. */
export default function Cadastros() {
  const { can } = useAuth();
  type T = "usuarios" | "jornadas" | "centrais";
  const tabs = ([["usuarios", "Pessoas", can("people.list")], ["jornadas", "Jornadas", true], ["centrais", "Centrais", can("kiosks.view")]] as [T, string, boolean][])
    .filter((t) => t[2]).map(([id, l]) => [id, l] as [T, string]);
  const [tab, setTab] = useState<T>(tabs[0]?.[0] ?? "jornadas");
  return (
    <>
      <h1 style={{ margin: 0 }}>Cadastros</h1>
      <Tabs label="Cadastros" tabs={tabs} tab={tab} onTab={setTab} />
      {tab === "usuarios" && <People />}
      {tab === "jornadas" && <Schedules readOnly={!can("schedules.manage")} />}
      {tab === "centrais" && <KiosksTab readOnly={!can("kiosks.manage")} />}
    </>
  );
}

/** Gestão > Empresa: fechamento do mês, fiscalização, configurações e auditoria (cada aba conforme a permissão). */
export function Empresa() {
  const { can } = useAuth();
  type T = "fechamento" | "fiscalizacao" | "configuracoes" | "auditoria";
  const tabs = ([
    ["fechamento", "Fechamento", can("closing.view")], ["fiscalizacao", "Fiscalização", can("fiscal.export") || can("integrity.view")],
    ["configuracoes", "Configurações", can("company.settings")], ["auditoria", "Auditoria", can("audit.view")],
  ] as [T, string, boolean][]).filter((t) => t[2]).map(([id, l]) => [id, l] as [T, string]);
  const [tab, setTab] = useState<T>(tabs[0]?.[0] ?? "fechamento");
  return (
    <>
      <h1 style={{ margin: 0 }}>Empresa</h1>
      <Tabs label="Empresa" tabs={tabs} tab={tab} onTab={setTab} />
      {tab === "fechamento" && <Closings readOnly={!can("closing.manage")} />}
      {tab === "fiscalizacao" && <Compliance />}
      {tab === "configuracoes" && <Settings />}
      {tab === "auditoria" && <Audit />}
    </>
  );
}

// --- Jornadas -----------------------------------------------------------------
function Schedules({ readOnly }: { readOnly: boolean }) {
  const [list, setList] = useState<Schedule[]>([]);
  const [name, setName] = useState("");
  const [days, setDays] = useState([0, 1, 2, 3, 4]);
  const [hours, setHours] = useState("8");
  const [brk, setBrk] = useState("60");
  const [tol, setTol] = useState("10");
  const [start, setStart] = useState("08:00");
  const [brkStart, setBrkStart] = useState("12:00");
  const [crosses, setCrosses] = useState(false);
  const [change, setChange] = useState<{ id: number; value: boolean } | null>(null); // confirmação na própria tela
  const [editing, setEditing] = useState<{ id: number; name: string; days: number[]; hours: string; brk: string; tol: string; start: string; brkStart: string } | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const n = useNotice();

  const load = useCallback(() => api<Schedule[]>("/schedules").then(setList).catch(n.fail), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function applyCrosses() {
    if (!change) return;
    try {
      await api(`/schedules/${change.id}`, { method: "PATCH", body: { crosses_midnight: change.value } });
      n.ok(change.value ? "Agora a jornada pode terminar no dia seguinte." : "Agora a jornada se encerra à meia-noite.");
      setChange(null);
      await load();
    } catch (err) {
      setChange(null);
      n.fail(err);
    }
  }

  async function saveSchedule(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    try {
      await api(`/schedules/${editing.id}`, {
        method: "PATCH",
        body: {
          name: editing.name, weekdays: editing.days, daily_minutes: Math.round(Number(editing.hours) * 60), break_minutes: Number(editing.brk),
          tolerance_minutes: Number(editing.tol), start_time: editing.start, break_start: editing.brkStart,
        },
      });
      n.ok("Jornada atualizada.");
      setEditing(null);
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  async function removeSchedule(id: number) {
    try {
      await api(`/schedules/${id}`, { method: "DELETE" });
      n.ok("Jornada excluída.");
      setRemoving(null);
      await load();
    } catch (err) {
      setRemoving(null);
      n.fail(err);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/schedules", {
        method: "POST",
        body: {
          name, weekdays: days, daily_minutes: Math.round(Number(hours) * 60), break_minutes: Number(brk),
          tolerance_minutes: Number(tol), start_time: start, break_start: brkStart, crosses_midnight: crosses,
        },
      });
      setName("");
      n.ok("Jornada criada.");
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  return (
    <>
      {n.el}
      {list.length === 0 && <p className="muted">Nenhuma jornada cadastrada.</p>}
      {list.map((s) => (
        <section className="card" key={s.id}>
          <strong>{s.name}</strong>
          <div className="quick" style={{ margin: "8px 0" }}>
            {DAYS.map((d, i) => (
              <span key={d} className={`pill ${s.weekdays.split(",").includes(String(i)) ? "" : "off-pill"}`}>{d}</span>
            ))}
            {s.crosses_midnight && <span className="pill warn-pill">Vira a meia-noite</span>}
          </div>
          <p className="muted small" style={{ margin: 0 }}>
            Entrada {s.start_time} · carga {fmtMinutes(s.daily_minutes)} ·{" "}
            {s.break_minutes > 0 ? `intervalo de ${s.break_minutes} min às ${s.break_start}` : "sem intervalo"} · tolerância {s.tolerance_minutes} min
          </p>
          {!readOnly && (
            <label className="check" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={!!s.crosses_midnight} onChange={(e) => setChange({ id: s.id, value: e.target.checked })} />
              <span>Pode terminar no dia seguinte (turno da noite)</span>
            </label>
          )}
          {!readOnly && (
            <div className="row" style={{ marginTop: 12 }}>
              <button onClick={() => setEditing({ id: s.id, name: s.name, days: s.weekdays.split(",").filter(Boolean).map(Number), hours: String(s.daily_minutes / 60),
                brk: String(s.break_minutes), tol: String(s.tolerance_minutes), start: s.start_time, brkStart: s.break_start })}>Editar jornada</button>
              <button className="danger" onClick={() => setRemoving(s.id)}>Excluir</button>
            </div>
          )}
          {removing === s.id && (
            <div className="alert info" role="alertdialog" aria-label="Confirmar exclusão da jornada" style={{ marginTop: 8 }}>
              <p style={{ margin: "0 0 8px" }}>Excluir a jornada “{s.name}”? Só é possível se nenhuma pessoa a usa. Não dá para desfazer.</p>
              <div className="row"><button className="danger" onClick={() => removeSchedule(s.id)}>Confirmar exclusão</button><button onClick={() => setRemoving(null)}>Voltar</button></div>
            </div>
          )}
          {editing?.id === s.id && (
            <form className="card" onSubmit={saveSchedule} style={{ marginTop: 8 }} aria-label={`Editar ${s.name}`}>
              <label>Nome<input required minLength={2} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></label>
              <p className="section-title">Dias de trabalho</p>
              <div className="quick" role="group" aria-label="Dias de trabalho">
                {DAYS.map((d, i) => (
                  <button type="button" key={d} className={`fchip ${editing.days.includes(i) ? "on" : ""}`} aria-pressed={editing.days.includes(i)}
                    onClick={() => setEditing({ ...editing, days: editing.days.includes(i) ? editing.days.filter((x) => x !== i) : [...editing.days, i] })}>{d}</button>
                ))}
              </div>
              <div className="grid2 keep">
                <label>Carga diária (h)<input type="number" min="0" max="12" step="0.25" value={editing.hours} onChange={(e) => setEditing({ ...editing, hours: e.target.value })} /></label>
                <label>Intervalo (min)<input type="number" min="0" max="240" value={editing.brk} onChange={(e) => setEditing({ ...editing, brk: e.target.value })} /></label>
                <label>Tolerância (máx. 10)<input type="number" min="0" max="10" value={editing.tol} onChange={(e) => setEditing({ ...editing, tol: e.target.value })} /></label>
                <label>Primeira entrada<input type="time" required value={editing.start} onChange={(e) => setEditing({ ...editing, start: e.target.value })} /></label>
                <label>Início do intervalo<input type="time" required value={editing.brkStart} onChange={(e) => setEditing({ ...editing, brkStart: e.target.value })} /></label>
              </div>
              <p className="muted small">Só o nome muda sem efeito no cálculo. As demais mudanças valem para o Espelho de dias ainda abertos e são recusadas se um mês fechado tiver marcações de pessoas desta jornada. Tudo fica na auditoria.</p>
              <div className="row"><button className="primary">Salvar</button><button type="button" onClick={() => setEditing(null)}>Cancelar</button></div>
            </form>
          )}
          {change?.id === s.id && (
            <div className="alert info" role="alertdialog" aria-label="Confirmar mudança da jornada" style={{ marginTop: 8 }}>
              <p style={{ margin: "0 0 8px" }}>
                {change.value
                  ? "Ligar: o turno aberto passa a continuar depois da meia-noite."
                  : "Desligar: a jornada passa a se encerrar à meia-noite; uma entrada sem saída vira “saída ausente”."}{" "}
                <b>O Espelho é recalculado também para dias já passados</b> ainda abertos. Se algum mês fechado tiver marcações de pessoas desta jornada, a mudança é recusada: reabra o mês antes. Fica na auditoria.
              </p>
              <div className="row">
                <button className="primary" onClick={applyCrosses}>Confirmar</button>
                <button onClick={() => setChange(null)}>Voltar</button>
              </div>
            </div>
          )}
        </section>
      ))}
      {!readOnly && (
        <details className="fold">
          <summary>Criar uma jornada</summary>
          <form className="card" onSubmit={create}>
            <label>Nome<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
            <p className="section-title">Dias de trabalho</p>
            <div className="quick" role="group" aria-label="Dias de trabalho">
              {DAYS.map((d, i) => (
                <button type="button" key={d} className={`fchip ${days.includes(i) ? "on" : ""}`} aria-pressed={days.includes(i)}
                  onClick={() => setDays(days.includes(i) ? days.filter((x) => x !== i) : [...days, i])}>{d}</button>
              ))}
            </div>
            <div className="grid2 keep">
              <label>Carga diária (h)<input type="number" min="0" max="12" step="0.25" value={hours} onChange={(e) => setHours(e.target.value)} /></label>
              <label>Intervalo (min)<input type="number" min="0" max="240" value={brk} onChange={(e) => setBrk(e.target.value)} /></label>
              <label>Tolerância (máx. 10)<input type="number" min="0" max="10" value={tol} onChange={(e) => setTol(e.target.value)} /></label>
              <label>Primeira entrada<input type="time" required value={start} onChange={(e) => setStart(e.target.value)} /></label>
              <label>Início do intervalo<input type="time" required value={brkStart} onChange={(e) => setBrkStart(e.target.value)} /></label>
            </div>
            <label className="check">
              <input type="checkbox" checked={crosses} onChange={(e) => setCrosses(e.target.checked)} />
              <span>
                A jornada pode terminar no dia seguinte (turno da noite)
                <span className="muted small" style={{ display: "block", fontWeight: 400 }}>
                  Desligado (padrão): a jornada se encerra à meia-noite. Uma entrada sem saída vira “saída ausente” e o dia seguinte recomeça em
                  entrada. Ligado: o turno que começou num dia pode ser encerrado no outro.
                </span>
              </span>
            </label>
            <button className="primary" style={{ width: "100%" }}>Criar jornada</button>
          </form>
        </details>
      )}
    </>
  );
}

// --- Fechamento ---------------------------------------------------------------
function Closings({ readOnly }: { readOnly: boolean }) {
  const { company } = useAuth();
  const [list, setList] = useState<Closing[]>([]);
  const [month, setMonth] = useState(() => shiftMonth(currentMonth(company!.timezone), -1));
  const [reopen, setReopen] = useState<string | null>(null);
  const n = useNotice();

  const load = useCallback(() => api<Closing[]>("/closings").then(setList).catch(n.fail), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function act(path: string, okText: string) {
    try {
      await api(path, { method: "POST" });
      n.ok(okText);
      setReopen(null);
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  return (
    <>
      {n.el}
      {!readOnly && (
        <section className="card">
          <h2 className="section-title">Fechar mês</h2>
          <p className="muted small">
            Exige que não haja ajustes ou ausências pendentes no mês e bloqueia novas alterações. Só o RH ou a Administração reabrem,
            e a reabertura fica na auditoria.
          </p>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Mês" style={{ margin: 0 }} />
            <button className="primary" style={{ flex: "none" }} onClick={() => act(`/closings/${month}`, `Mês ${month} fechado.`)}>Fechar</button>
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="h-fechados">
        <h2 id="h-fechados" className="section-title">Meses fechados</h2>
        {list.length === 0 && <p className="muted" style={{ margin: 0 }}>Nenhum mês fechado.</p>}
        <ul className="plain">
          {list.map((c) => (
            <li key={c.month} className="request">
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                <strong>{c.month.split("-").reverse().join("/")}</strong>
                <span className={`tag ${c.status === "closed" ? "approved" : "pending"}`}>{c.status === "closed" ? "Fechado" : "Reaberto"}</span>
              </div>
              {!readOnly && c.status === "closed" && (
                reopen === c.month ? (
                  <div className="row request-actions">
                    <button className="danger" onClick={() => act(`/closings/${c.month}/reopen`, `Mês ${c.month} reaberto.`)}>Confirmar reabertura</button>
                    <button onClick={() => setReopen(null)}>Voltar</button>
                  </div>
                ) : (
                  <button className="link" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setReopen(c.month)}>Reabrir</button>
                )
              )}
            </li>
          ))}
        </ul>
      </section>

    </>
  );
}

// --- Auditoria ----------------------------------------------------------------
function Audit() {
  const { company } = useAuth();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [entity, setEntity] = useState("");
  const n = useNotice();
  useEffect(() => {
    api<AuditRow[]>(`/audit?limit=100${entity ? `&entity=${entity}` : ""}`).then(setRows).catch(n.fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity]);
  return (
    <>
      {n.el}
      <label>Filtrar por tipo de registro
        <select value={entity} onChange={(e) => setEntity(e.target.value)}>
          <option value="">Todos</option>
          {["user", "punch", "adjustment", "absence", "closing", "schedule", "company", "hour_bank_entry", "kiosk"].map((x) => <option key={x}>{x}</option>)}
        </select>
      </label>
      <section className="card" style={{ padding: "4px 16px" }}>
        {rows.length === 0 && <p className="muted">Nada registrado.</p>}
        <ul className="plain">
          {rows.map((r) => (
            <li key={r.id} className="request" style={{ padding: "12px 0" }}>
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                <span><strong>{ACTION_LABEL[r.action] ?? r.action}</strong> <span className="muted">{r.entity}{r.entity_id ? ` #${r.entity_id}` : ""}</span></span>
                <span className="muted small" style={{ flex: "none" }}>{fmtDateTime(r.at, company!.timezone)}</span>
              </div>
              <span className="muted small">Autor: {r.actor_id ?? "sistema"}{r.ip ? ` · ${r.ip}` : ""}</span>
              {r.after != null && <code className="audit-json">{JSON.stringify(r.after)}</code>}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

// --- Fiscalização ---------------------------------------------------------------
function Compliance() {
  const { company, can } = useAuth();
  const [integrity, setIntegrity] = useState<{ ok: boolean; checked: number; problems: string[] } | null>(null);
  const tz = company!.timezone;
  const [start, setStart] = useState(() => `${shiftMonth(currentMonth(tz), -1)}-01`);
  const [end, setEnd] = useState(() => todayLocal(tz));
  const [signed, setSigned] = useState(false);
  const [status, setStatus] = useState<{ ready: boolean; issues: string[]; signing_configured: boolean } | null>(null);
  const [busy, setBusy] = useState("");
  const n = useNotice();

  useEffect(() => {
    api<NonNullable<typeof status>>("/exports/status").then(setStatus).catch(n.fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function get(kind: "afd" | "aej") {
    setBusy(kind);
    try {
      await download(`/exports/${kind}?start=${start}&end=${end}${signed ? "&signed=true" : ""}`, `${kind.toUpperCase()}.txt`);
      n.ok(`${kind.toUpperCase()} gerado.`);
    } catch (err) {
      n.fail(err);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      {n.el}
      {status && status.issues.length > 0 && (
        <div className="alert error" role="alert">
          <strong>Pendências antes de emitir arquivos conformes:</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>{status.issues.map((i) => <li key={i}>{i}</li>)}</ul>
        </div>
      )}
      {status?.ready && <p className="alert ok" role="status">Configuração completa.</p>}
      <section className="card">
        <h2 className="section-title">Arquivos para a fiscalização</h2>
        <p className="muted small">
          AFD (Anexo V) e AEJ (Anexo VI) da Portaria MTP 671/2021, para entregar ao Auditor-Fiscal do Trabalho quando solicitados.
        </p>
        <div className="grid2 keep">
          <label>De<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Até<input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
        <label className="check">
          <input type="checkbox" checked={signed} disabled={!status?.signing_configured} onChange={(e) => setSigned(e.target.checked)} />
          <span>Assinar com certificado ICP-Brasil (baixa um .zip com o arquivo e a assinatura .p7s)</span>
        </label>
        <div className="row">
          <button className="primary" disabled={!!busy} onClick={() => get("afd")}>{busy === "afd" ? "Gerando…" : "Baixar AFD"}</button>
          <button className="primary" disabled={!!busy} onClick={() => get("aej")}>{busy === "aej" ? "Gerando…" : "Baixar AEJ"}</button>
        </div>
      </section>

      {can("integrity.view") && (
      <section className="card">
        <h2 className="section-title">Integridade das marcações</h2>
        <p className="muted small">Confere se o NSR é contínuo e se a cadeia de hashes das marcações está intacta.</p>
        <button onClick={() => api<typeof integrity>("/punches-integrity").then(setIntegrity).catch(n.fail)}>Verificar agora</button>
        {integrity && (
          <p className={`alert ${integrity.ok ? "ok" : "error"}`} role="status" style={{ marginTop: 12 }}>
            {integrity.ok ? `Íntegro: ${integrity.checked} marcações verificadas.` : `Problemas: ${integrity.problems.join("; ")}`}
          </p>
        )}
      </section>
      )}
    </>
  );
}

function KiosksTab({ readOnly }: { readOnly: boolean }) {
  const n = useNotice();
  return (
    <>
      {n.el}
      <Kiosks readOnly={readOnly} notify={{ ok: n.ok, fail: n.fail }} />
    </>
  );
}
