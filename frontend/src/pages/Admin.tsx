import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, api, download } from "../api";
import { useAuth } from "../auth";
import type { AuditRow, Closing, ImportResult, Schedule, User } from "../types";
import Kiosks from "./Kiosks";
import { ROLE_LABEL, currentMonth, fmtCpf, fmtDateTime, fmtMinutes, initials, shiftMonth, todayLocal } from "../util";

type Tab = "usuarios" | "centrais" | "jornadas" | "fechamento" | "fiscalizacao" | "auditoria";
const TABS: [Tab, string][] = [
  ["usuarios", "Pessoas"], ["centrais", "Centrais"], ["jornadas", "Jornadas"], ["fechamento", "Fechamento"], ["fiscalizacao", "Fiscalização"], ["auditoria", "Auditoria"],
];
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

export default function Admin() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("usuarios");
  const readOnly = user?.role === "auditor";
  return (
    <>
      <h1 style={{ margin: 0 }}>Gestão</h1>
      <div className="seg scroll-x" role="tablist" aria-label="Áreas da gestão" style={{ margin: "14px 0" }}>
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "usuarios" && <Users readOnly={readOnly} />}
      {tab === "jornadas" && <Schedules readOnly={readOnly} />}
      {tab === "fechamento" && <Closings readOnly={readOnly} />}
      {tab === "fiscalizacao" && <Compliance />}
      {tab === "centrais" && <KiosksTab readOnly={readOnly} />}
      {tab === "auditoria" && <Audit />}
    </>
  );
}

// --- Pessoas ------------------------------------------------------------------
function Users({ readOnly }: { readOnly: boolean }) {
  const { user } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [f, setF] = useState({ name: "", email: "", password: "", cpf: "", role: "employee", manager_id: "", schedule_id: "", admitted_at: "", job_title: "" });
  const [query, setQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null); // "<ação>-<id>": confirmação na própria tela
  const [edit, setEdit] = useState<{ id: number; name: string; email: string; cpf: string; job_title: string } | null>(null);
  const [newSchedule, setNewSchedule] = useState<{ id: number; value: string } | null>(null); // troca de jornada em confirmação
  const [scheduleError, setScheduleError] = useState("");
  const [temp, setTemp] = useState<{ name: string; password: string } | null>(null);
  const n = useNotice();

  const load = useCallback(async () => {
    try {
      const [u, s] = await Promise.all([api<User[]>("/users"), api<Schedule[]>("/schedules")]);
      setUsers(u);
      setSchedules(s);
    } catch (e) {
      n.fail(e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/users", {
        method: "POST",
        body: {
          name: f.name, email: f.email, password: f.password, cpf: f.cpf, role: f.role,
          manager_id: f.manager_id ? Number(f.manager_id) : null,
          schedule_id: f.schedule_id ? Number(f.schedule_id) : null,
          admitted_at: f.admitted_at || null,
          job_title: f.job_title || null,
        },
      });
      setF({ ...f, name: "", email: "", password: "", cpf: "" });
      n.ok("Colaborador cadastrado.");
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  async function patch(u: User, body: object, okText: string) {
    try {
      await api(`/users/${u.id}`, { method: "PATCH", body });
      n.ok(okText);
      setConfirm(null);
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  async function saveEdit(e: FormEvent) {
    e.preventDefault();
    if (!edit) return;
    const u = users.find((x) => x.id === edit.id)!;
    const body: Record<string, string> = {};
    if (edit.name.trim() !== u.name) body.name = edit.name.trim();
    if (edit.email.trim().toLowerCase() !== u.email) body.email = edit.email.trim();
    if (edit.cpf.replace(/\D/g, "") !== u.cpf) body.cpf = edit.cpf;
    if (edit.job_title.trim() !== (u.job_title ?? "")) body.job_title = edit.job_title.trim();
    if (Object.keys(body).length === 0) return setEdit(null);
    try {
      await api(`/users/${u.id}`, { method: "PATCH", body });
      n.ok("Cadastro atualizado.");
      setEdit(null);
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  async function removeUser(u: User) {
    try {
      await api(`/users/${u.id}`, { method: "DELETE" });
      n.ok(`${u.name} excluída(o) do cadastro.`);
      setConfirm(null);
      await load();
    } catch (err) {
      setConfirm(null);
      n.fail(err);
    }
  }

  async function changeSchedule(u: User) {
    if (!newSchedule) return;
    try {
      await api(`/users/${u.id}`, { method: "PATCH", body: { schedule_id: Number(newSchedule.value) } });
      n.ok(`Jornada de ${u.name} trocada.`);
      setNewSchedule(null);
      setScheduleError("");
      await load();
    } catch (err) {
      setScheduleError(err instanceof Error ? err.message : "Erro ao trocar a jornada"); // ex.: mês fechado com marcações dela
    }
  }

  const [badges, setBadges] = useState<Record<number, { employee_code: string; has_pin: boolean }>>({});

  async function loadBadge(id: number) {
    try {
      const b = await api<{ employee_code: string; has_pin: boolean }>(`/users/${id}/badge`);
      setBadges((m) => ({ ...m, [id]: b }));
    } catch {
      /* sem permissão para esta conta: só não mostra */
    }
  }

  async function badgeAction(u: User, path: string, okText: string) {
    try {
      await api(`/users/${u.id}/${path}`, { method: "POST" });
      n.ok(okText);
      setConfirm(null);
      await loadBadge(u.id);
    } catch (err) {
      n.fail(err);
    }
  }

  async function resetPassword(u: User) {
    try {
      setTemp(await api<{ name: string; password: string }>(`/users/${u.id}/reset-password`, { method: "POST" }));
      setConfirm(null);
    } catch (err) {
      n.fail(err);
    }
  }

  async function resetTwoFactor(u: User) {
    try {
      await api(`/users/${u.id}/reset-2fa`, { method: "POST" });
      n.ok("2FA removido. A pessoa poderá configurá-lo de novo em Minha conta.");
      setConfirm(null);
      await load();
    } catch (err) {
      n.fail(err);
    }
  }

  // Só dois perfis de uso: colaborador e administrador (master: gestão, RH, aprovações, centrais). Auditor = leitura para a fiscalização.
  const roles = user?.role === "admin" ? ["employee", "admin", "auditor"] : ["employee"];
  const managers = users.filter((u) => u.active && ["admin", "hr", "manager"].includes(u.role));
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users.filter((u) => (showInactive || u.active) && (!q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)));
  }, [users, query, showInactive]);
  const scheduleName = (id: number | null) => schedules.find((s) => s.id === id)?.name;

  const Confirm = ({ id, text, danger, onYes }: { id: string; text: string; danger?: boolean; onYes: () => void }) =>
    confirm === id ? (
      <div className="alert info" role="alertdialog" aria-label={text}>
        <p style={{ margin: "0 0 8px" }}>{text}</p>
        <div className="row">
          <button className={danger ? "danger" : "primary"} onClick={onYes}>Confirmar</button>
          <button onClick={() => setConfirm(null)}>Voltar</button>
        </div>
      </div>
    ) : null;

  return (
    <>
      {n.el}
      {temp && (
        <div className="alert info" role="status">
          <strong>Senha temporária de {temp.name}:</strong> <code style={{ fontSize: "1.1rem" }}>{temp.password}</code>
          <p className="small" style={{ margin: "4px 0 8px" }}>Aparece só agora. A pessoa será obrigada a trocá-la no primeiro acesso.</p>
          <div className="row"><button onClick={() => navigator.clipboard?.writeText(temp.password)}>Copiar</button><button className="primary" onClick={() => setTemp(null)}>Fechar</button></div>
        </div>
      )}

      {!readOnly && (
        <div className="row" style={{ marginBottom: 8 }}>
          <button onClick={() => download("/badges.pdf", "crachas.pdf").catch((e) => n.fail(e))}>Crachás de todos (PDF)</button>
        </div>
      )}
      <label className="search">
        <span className="sr-only">Buscar pessoa</span>
        <input type="search" placeholder="Buscar por nome ou e-mail" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap", margin: "0 0 8px" }}>
        <span className="muted small">{shown.length} pessoa(s)</span>
        <button className="link" style={{ minHeight: 32, flex: "none" }} onClick={() => setShowInactive(!showInactive)} aria-pressed={showInactive}>
          {showInactive ? "Ocultar inativos" : "Mostrar inativos"}
        </button>
      </div>

      <section className="card" style={{ padding: "4px 16px" }}>
        {shown.length === 0 && <p className="muted">Ninguém encontrado.</p>}
        {shown.map((u) => (
          <details className="day-row" key={u.id} onToggle={(e) => e.currentTarget.open && !readOnly && void loadBadge(u.id)}>
            <summary>
              <span className="avatar" aria-hidden="true">{initials(u.name)}</span>
              <span className="day-main">
                <strong>{u.name}</strong>
                <span className="muted small">{u.job_title ? `${u.job_title} · ` : ""}{u.email}</span>
              </span>
              <span className="day-num" style={{ alignItems: "flex-end", gap: 4 }}>
                {u.role !== "employee" && <span className="tag">{ROLE_LABEL[u.role]}</span>}
                {!u.active && <span className="tag falta">Inativo</span>}
              </span>
            </summary>
            <div className="day-body" style={{ paddingLeft: 0 }}>
              <dl className="receipt small" style={{ marginBottom: 8 }}>
                <dt>CPF</dt><dd>{fmtCpf(u.cpf)}</dd>
                <dt>Jornada</dt>
                <dd>
                  {readOnly ? (scheduleName(u.schedule_id) ?? "—") : (
                    <select aria-label={`Jornada de ${u.name}`} value={newSchedule?.id === u.id ? newSchedule.value : (u.schedule_id ?? "")}
                      style={{ margin: 0, minHeight: 40 }}
                      onChange={(e) => { setScheduleError(""); setNewSchedule(e.target.value && Number(e.target.value) !== u.schedule_id ? { id: u.id, value: e.target.value } : null); }}>
                      {u.schedule_id === null && <option value="" disabled>Sem jornada</option>}
                      {schedules.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  )}
                </dd>
                <dt>Bate ponto em</dt>
                <dd>
                  {readOnly ? (u.punch_policy === "kiosk" ? "Só a Central" : "Aplicativo e Central") : (
                    <select aria-label={`Onde ${u.name} registra o ponto`} value={u.punch_policy === "kiosk" ? "kiosk" : "both"}
                      onChange={(e) => patch(u, { punch_policy: e.target.value }, e.target.value === "kiosk" ? "Agora só a Central registra o ponto desta pessoa." : "Esta pessoa volta a registrar também pelo aplicativo.")}>
                      <option value="both">Aplicativo e Central</option>
                      <option value="kiosk">Só a Central</option>
                    </select>
                  )}
                </dd>
                <dt>Banco de horas</dt><dd>{u.hour_bank_enabled ? "Ativo" : "Não usa"}</dd>
                <dt>2FA</dt><dd>{u.totp_enabled ? "Ativo" : "Não"}</dd>
                {!readOnly && badges[u.id] && (
                  <>
                    <dt>Código (Central)</dt><dd><code>{badges[u.id].employee_code}</code></dd>
                    <dt>PIN da Central</dt><dd>{badges[u.id].has_pin ? "Definido" : "Não definido"}</dd>
                  </>
                )}
              </dl>
              {!readOnly && newSchedule?.id === u.id && (
                <div className="alert info" role="alertdialog" aria-label="Confirmar troca de jornada">
                  <p style={{ margin: "0 0 8px" }}>
                    Trocar a jornada de {u.name} para <b>{scheduleName(Number(newSchedule.value))}</b>? O Espelho dela passa a ser calculado com a nova
                    jornada. Se houver mês fechado com marcações dela, a troca é recusada: reabra o mês antes.
                  </p>
                  {scheduleError && <p className="alert error" role="alert">{scheduleError}</p>}
                  <div className="row">
                    <button className="primary" onClick={() => changeSchedule(u)}>Confirmar troca</button>
                    <button onClick={() => { setNewSchedule(null); setScheduleError(""); }}>Voltar</button>
                  </div>
                </div>
              )}
              {!readOnly && (
                <>
                  <div className="row">
                    <button onClick={() => patch(u, { hour_bank_enabled: !u.hour_bank_enabled },
                      u.hour_bank_enabled ? "Banco de horas desativado (o histórico é mantido)." : "Banco de horas ativado; o saldo conta a partir de hoje.")}>
                      {u.hour_bank_enabled ? "Desativar banco de horas" : "Ativar banco de horas"}
                    </button>
                    <button onClick={() => download(`/users/${u.id}/badge.pdf`, `cracha-${u.id}.pdf`).catch((e) => n.fail(e))}>Baixar crachá (PDF)</button>
                    {badges[u.id]?.has_pin && <button onClick={() => setConfirm(`pin-${u.id}`)}>Zerar PIN</button>}
                    <button onClick={() => setConfirm(`badge-${u.id}`)}>Regenerar crachá</button>
                    <button onClick={() => setEdit({ id: u.id, name: u.name, email: u.email, cpf: fmtCpf(u.cpf), job_title: u.job_title ?? "" })}>Editar dados</button>
                    {u.id !== user?.id && <button onClick={() => setConfirm(`pw-${u.id}`)}>Nova senha</button>}
                    {u.id !== user?.id && u.totp_enabled && <button onClick={() => setConfirm(`2fa-${u.id}`)}>Zerar 2FA</button>}
                    {u.id !== user?.id && (
                      <button className={u.active ? "danger" : ""} onClick={() => setConfirm(`act-${u.id}`)}>{u.active ? "Desativar pessoa" : "Reativar pessoa"}</button>
                    )}
                    {u.id !== user?.id && <button className="danger" onClick={() => setConfirm(`del-${u.id}`)}>Excluir cadastro</button>}
                  </div>
                  {edit?.id === u.id && (
                    <form className="card" onSubmit={saveEdit} style={{ marginTop: 8 }} aria-label={`Editar ${u.name}`}>
                      <label>Nome<input required minLength={2} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
                      <label>E-mail (usado para entrar)<input type="email" required value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></label>
                      <label>CPF<input required inputMode="numeric" value={edit.cpf} onChange={(e) => setEdit({ ...edit, cpf: e.target.value })} /></label>
                      <p className="muted small" style={{ margin: "0 0 8px" }}>O CPF só pode ser corrigido enquanto a pessoa não tem marcações (ele faz parte de cada registro). Nome e CPF alterados ficam registrados no REP-P (tipo 5).</p>
                      <label>Cargo ou função<input maxLength={100} value={edit.job_title} onChange={(e) => setEdit({ ...edit, job_title: e.target.value })} /></label>
                      <div className="row"><button className="primary">Salvar</button><button type="button" onClick={() => setEdit(null)}>Cancelar</button></div>
                    </form>
                  )}
                  <Confirm id={`del-${u.id}`} danger text={`Excluir o cadastro de ${u.name}? Só é possível se a pessoa nunca teve marcações, ajustes, ausências ou banco de horas (cadastro feito por engano). Não dá para desfazer. Quem já trabalhou deve ser desativado ("Desativar pessoa"), para manter o histórico.`} onYes={() => removeUser(u)} />
                  <Confirm id={`pin-${u.id}`} text={`Zerar o PIN de ${u.name}? Ela define outro em Minha conta.`} onYes={() => badgeAction(u, "pin-reset", "PIN zerado.")} />
                  <Confirm id={`badge-${u.id}`} danger text={`Regenerar o crachá de ${u.name}? O QR impresso atual deixa de funcionar na Central; imprima o novo.`} onYes={() => badgeAction(u, "badge/regenerate", "Crachá regenerado: o impresso anterior não vale mais.")} />
                  <Confirm id={`pw-${u.id}`} text={`Gerar uma senha temporária para ${u.name}? A senha atual deixa de valer e as sessões abertas caem.`} onYes={() => resetPassword(u)} />
                  <Confirm id={`2fa-${u.id}`} text={`Remover a verificação em duas etapas de ${u.name}? Use só se ela perdeu o celular e os códigos de recuperação.`} onYes={() => resetTwoFactor(u)} />
                  <Confirm id={`act-${u.id}`} danger={u.active} text={u.active ? `Desativar ${u.name}? A pessoa não consegue mais entrar; o histórico é mantido.` : `Reativar ${u.name}?`}
                    onYes={() => patch(u, { active: !u.active }, u.active ? "Pessoa desativada." : "Pessoa reativada.")} />
                </>
              )}
            </div>
          </details>
        ))}
      </section>

      {!readOnly && (
        <details className="fold">
          <summary>Cadastrar um colaborador</summary>
          <form className="card" onSubmit={create}>
            <div className="grid2">
              <label>Nome<input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
              <label>E-mail<input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
              <label>CPF<input required inputMode="numeric" placeholder="000.000.000-00" value={f.cpf} onChange={(e) => setF({ ...f, cpf: e.target.value })} /></label>
              <label>Cargo ou função<input maxLength={100} value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} /></label>
              <label>Data de admissão<input type="date" value={f.admitted_at} onChange={(e) => setF({ ...f, admitted_at: e.target.value })} /></label>
              <label>Senha inicial<input type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
              <label>Perfil
                <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                  {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
              </label>
              <label>Gestor
                <select value={f.manager_id} onChange={(e) => setF({ ...f, manager_id: e.target.value })}>
                  <option value="">—</option>
                  {managers.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              </label>
              <label>Jornada
                <select value={f.schedule_id} onChange={(e) => setF({ ...f, schedule_id: e.target.value })}>
                  <option value="">—</option>
                  {schedules.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>
            </div>
            <button className="primary" style={{ width: "100%" }}>Cadastrar</button>
          </form>
        </details>
      )}
      {!readOnly && (
        <details className="fold">
          <summary>Importar vários por CSV</summary>
          <ImportCard onDone={load} />
        </details>
      )}
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
  const { company, user, reload } = useAuth();
  const [list, setList] = useState<Closing[]>([]);
  const [month, setMonth] = useState(() => shiftMonth(currentMonth(company!.timezone), -1));
  const [integrity, setIntegrity] = useState<{ ok: boolean; checked: number; problems: string[] } | null>(null);
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
            Exige que não haja ajustes ou ausências pendentes no mês e bloqueia novas alterações. Só o RH ou o administrador reabre,
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

      {user?.role === "admin" && (
        <section className="card" aria-labelledby="h-foto">
          <h2 id="h-foto" className="section-title">Foto na batida</h2>
          <p className="muted small">
            Opcional. Cada pessoa autoriza a própria foto (LGPD); se a câmera falhar ou a pessoa recusar, o ponto é registrado do mesmo jeito.
            As fotos são criptografadas, só o RH e o administrador as veem e <b>são apagadas quando o mês é fechado</b>. As marcações nunca são apagadas.
          </p>
          <label className="check">
            <input type="checkbox" checked={!!company?.photo_enabled} onChange={async (e) => {
              try {
                await api("/company", { method: "PATCH", body: { photo_enabled: e.target.checked } });
                await reload();
                n.ok(e.target.checked ? "Foto na batida ativada." : "Foto na batida desativada (as já tiradas seguem até o fechamento do mês).");
              } catch (err) {
                n.fail(err);
              }
            }} />
            <span>Permitir foto na batida nesta empresa</span>
          </label>
        </section>
      )}

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
  const { company } = useAuth();
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
    </>
  );
}

// --- Importação CSV -------------------------------------------------------------
function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function ImportCard({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<{ name: string; b64: string } | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function pick(f: File | undefined) {
    setResult(null);
    setError("");
    setFile(f ? { name: f.name, b64: toBase64(await f.arrayBuffer()) } : null);
  }

  async function run(dry: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const r = await api<ImportResult>(`/users/import?dry_run=${dry}`, { method: "POST", body: { content_base64: file.b64 } });
      setResult(r);
      if (r.imported) onDone();
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === "object" && "errors" in err.data) setResult(err.data as ImportResult);
      else setError(err instanceof Error ? err.message : "Erro");
    } finally {
      setBusy(false);
    }
  }

  function downloadCredentials() {
    const rows = ["nome;email;senha_temporaria", ...(result?.credentials ?? []).map((c) => `${c.name};${c.email};${c.password}`)];
    const url = URL.createObjectURL(new Blob(["﻿" + rows.join("\n") + "\n"], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "senhas-temporarias.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="card">
      <p className="muted small">
        Colunas: nome, email, cpf (obrigatórias); cargo, gestor (e-mail), jornada (nome), perfil, admissao (dd/mm/aaaa) e codigo (interno da Central, de 4 a 10 números; se vazio, é gerado).
        Salvo do Excel em CSV serve. Primeiro valide; a importação grava tudo ou nada, até 200 linhas.
      </p>
      <div className="row">
        <button onClick={() => download("/users/import/template", "modelo-colaboradores.csv").catch((e) => setError(e.message))}>Baixar modelo</button>
        <input type="file" accept=".csv,text/csv" aria-label="Arquivo CSV" onChange={(e) => pick(e.target.files?.[0])} />
      </div>
      {error && <p className="alert error" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      {file && !result?.imported && (
        <div className="row" style={{ marginTop: 12 }}>
          <button disabled={busy} onClick={() => run(true)}>{busy ? "Validando…" : "Validar arquivo"}</button>
          <button className="primary" disabled={busy || !result || result.errors.length > 0 || result.valid === 0 || !result.dry_run}
            onClick={() => run(false)}>Importar {result && result.errors.length === 0 ? result.valid : ""}</button>
        </div>
      )}

      {result && !result.imported && (
        result.errors.length === 0 ? (
          <p className="alert ok" role="status" style={{ marginTop: 12 }}>
            {result.valid} colaborador(es) prontos para importar. Nada foi gravado ainda.
          </p>
        ) : (
          <div style={{ marginTop: 12 }}>
            <p className="alert error" role="alert">
              {result.errors.length} problema(s) em {result.total} linha(s). Corrija o arquivo e valide de novo; nada foi gravado.
            </p>
            <div className="scroll"><table>
              <thead><tr><th>Linha</th><th>Campo</th><th>Problema</th></tr></thead>
              <tbody>{result.errors.map((e, i) => <tr key={i}><td>{e.line}</td><td>{e.field}</td><td>{e.message}</td></tr>)}</tbody>
            </table></div>
          </div>
        )
      )}

      {result?.imported && (
        <div style={{ marginTop: 12 }}>
          <p className="alert ok" role="status">{result.created} colaborador(es) importados.</p>
          <div className="alert info">
            <strong>Senhas temporárias: aparecem só agora.</strong> Entregue cada uma à pessoa por um canal seguro; ela será
            obrigada a trocá-la no primeiro acesso. Não ficam guardadas em lugar nenhum.
            <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={downloadCredentials}>Baixar senhas (.csv)</button></div>
          </div>
          <div className="scroll"><table>
            <thead><tr><th>Nome</th><th>E-mail</th><th>Senha temporária</th></tr></thead>
            <tbody>{result.credentials.map((c) => <tr key={c.email}><td>{c.name}</td><td>{c.email}</td><td><code>{c.password}</code></td></tr>)}</tbody>
          </table></div>
        </div>
      )}
    </section>
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
