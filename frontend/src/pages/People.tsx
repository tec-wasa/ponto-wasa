import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, api, download } from "../api";
import { useAuth } from "../auth";
import type { ImportResult, Schedule, User } from "../types";
import { ROLE_LABEL, fmtCpf, initials } from "../util";

/** Gestão > Cadastros > Pessoas: lista, um formulário único para criar e editar, crachás, senhas e importação. */

function useNotice() {
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const fail = (e: unknown) => setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
  const ok = (text: string) => setMsg({ type: "ok", text });
  const el = msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>;
  return { ok, fail, el };
}

const FUNCS: [string, string][] = [
  ["admin", "tudo: empresa, configurações, centrais, permissões e auditoria (inclui RH e Gestor)"],
  ["hr", "cadastros, jornadas, ausências, banco de horas, fechamento, relatórios e arquivos fiscais da empresa toda"],
  ["manager", "acompanha a própria equipe e aprova os ajustes e ausências dela"],
];
const funcsOf = (u: User) => (u.roles?.length ? u.roles : u.role !== "employee" ? [u.role] : []).filter((r) => r !== "auditor");

type Form = {
  name: string; cpf: string; job_title: string; tracks_time: boolean; admitted_at: string; schedule_id: string; manager_id: string;
  punch_policy: "both" | "kiosk"; hour_bank_enabled: boolean; app_access: boolean; email: string; password: string; roles: string[];
};
const EMPTY: Form = {
  name: "", cpf: "", job_title: "", tracks_time: true, admitted_at: "", schedule_id: "", manager_id: "", punch_policy: "both",
  hour_bank_enabled: false, app_access: true, email: "", password: "", roles: [],
};
const fromUser = (u: User): Form => ({
  name: u.name, cpf: fmtCpf(u.cpf), job_title: u.job_title ?? "", tracks_time: u.tracks_time !== false, admitted_at: u.admitted_at ?? "",
  schedule_id: u.schedule_id ? String(u.schedule_id) : "", manager_id: u.manager_id ? String(u.manager_id) : "",
  punch_policy: u.punch_policy === "kiosk" ? "kiosk" : "both", hour_bank_enabled: u.hour_bank_enabled, app_access: u.app_access !== false,
  email: u.email ?? "", password: "", roles: funcsOf(u),
});

/** O formulário da pessoa, igual para cadastrar e para editar. Em edição, envia só o que mudou. */
function PersonForm({ user, people, schedules, onSaved, onCancel }: {
  user?: User; people: User[]; schedules: Schedule[]; onSaved: (text: string) => void; onCancel?: () => void;
}) {
  const { can } = useAuth();
  const admin = can("people.permissions");
  const [f, setF] = useState<Form>(user ? fromUser(user) : EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Form>) => setF((x) => ({ ...x, ...patch }));
  const managers = people.filter((p) => p.active && p.id !== user?.id && funcsOf(p).length > 0);
  const mustLogin = f.roles.length > 0 || !f.tracks_time; // gestão ou cadastro só de gestão precisam entrar no app

  function toggleRole(r: string) {
    set({ roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r], ...(f.roles.includes(r) ? {} : { app_access: true }) });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const body: Record<string, unknown> = {
      name: f.name.trim(), cpf: f.cpf, job_title: f.job_title.trim() || null, tracks_time: f.tracks_time, app_access: f.app_access,
      email: f.email.trim() || null,
      admitted_at: f.admitted_at || null, schedule_id: f.schedule_id ? Number(f.schedule_id) : null,
      manager_id: f.manager_id ? Number(f.manager_id) : null,
      punch_policy: f.app_access ? f.punch_policy : "kiosk", hour_bank_enabled: f.tracks_time && f.hour_bank_enabled,
      ...(admin ? { roles: f.roles } : {}),
    };
    if (!user) body.password = f.app_access ? f.password : null;
    let send = body;
    if (user) { // edição: só o que mudou
      const was = fromUser(user);
      const orig: Record<string, unknown> = {
        name: was.name, cpf: user.cpf, job_title: user.job_title, tracks_time: was.tracks_time, app_access: was.app_access, email: user.email,
        admitted_at: user.admitted_at, schedule_id: user.schedule_id, manager_id: user.manager_id, punch_policy: was.punch_policy,
        hour_bank_enabled: user.hour_bank_enabled, roles: was.roles,
      };
      send = Object.fromEntries(Object.entries(body).filter(([k, v]) => {
        if (k === "cpf") return String(v).replace(/\D/g, "") !== user.cpf;
        if (k === "roles") return [...(v as string[])].sort().join() !== [...(orig.roles as string[])].sort().join();
        if (k === "email") return (v ?? "") !== (orig.email ?? "") && v !== null;
        return (v ?? null) !== (orig[k] ?? null);
      }));
      if (Object.keys(send).length === 0) return onCancel?.();
    }
    setBusy(true);
    try {
      await api(user ? `/users/${user.id}` : "/users", { method: user ? "PATCH" : "POST", body: send });
      if (!user) setF(EMPTY);
      const enabledAccess = user && send.app_access === true;
      onSaved(user ? (enabledAccess ? "Cadastro atualizado. Para o primeiro acesso, gere uma senha em “Nova senha”." : "Cadastro atualizado.") : "Pessoa cadastrada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label={user ? `Editar ${user.name}` : "Cadastrar pessoa"} style={user ? { marginTop: 8 } : undefined}>
      {error && <p className="alert error" role="alert">{error}</p>}
      <p className="section-title">Dados</p>
      <div className="grid2">
        <label>Nome<input required minLength={2} maxLength={200} value={f.name} onChange={(e) => set({ name: e.target.value })} /></label>
        <label>CPF<input required inputMode="numeric" placeholder="000.000.000-00" value={f.cpf} onChange={(e) => set({ cpf: e.target.value })} /></label>
        <label>Cargo ou função<input maxLength={100} value={f.job_title} onChange={(e) => set({ job_title: e.target.value })} /></label>
      </div>
      {user && <p className="muted small" style={{ marginTop: 0 }}>O CPF só pode ser corrigido enquanto a pessoa não tem marcações. Nome e CPF alterados ficam registrados no REP-P.</p>}

      <p className="section-title" style={{ marginTop: 12 }}>Ponto</p>
      <label className="check">
        <input type="checkbox" checked={f.tracks_time} disabled={!admin && !f.tracks_time}
          onChange={(e) => set({ tracks_time: e.target.checked, ...(e.target.checked ? {} : { hour_bank_enabled: false, app_access: true }) })} />
        <span>Registra ponto<span className="muted small" style={{ display: "block", fontWeight: 400 }}>Desmarque para quem só faz a gestão (não tem espelho nem banco de horas).</span></span>
      </label>
      {f.tracks_time && (
        <div className="grid2">
          <label>Data de admissão<input type="date" value={f.admitted_at} onChange={(e) => set({ admitted_at: e.target.value })} /></label>
          <label>Jornada
            <select value={f.schedule_id} onChange={(e) => set({ schedule_id: e.target.value })}>
              <option value="">Sem jornada</option>
              {schedules.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label>Gestor
            <select value={f.manager_id} onChange={(e) => set({ manager_id: e.target.value })}>
              <option value="">Nenhum (o RH ou a Administração aprovam)</option>
              {managers.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label>Onde bate o ponto
            <select value={f.app_access ? f.punch_policy : "kiosk"} disabled={!f.app_access} onChange={(e) => set({ punch_policy: e.target.value as Form["punch_policy"] })}>
              <option value="both">Aplicativo e Central</option>
              <option value="kiosk">Só na Central</option>
            </select>
          </label>
          <label className="check" style={{ gridColumn: "1 / -1" }}>
            <input type="checkbox" checked={f.hour_bank_enabled} onChange={(e) => set({ hour_bank_enabled: e.target.checked })} />
            <span>Usa banco de horas<span className="muted small" style={{ display: "block", fontWeight: 400 }}>Ao ativar, o saldo começa a contar a partir de hoje. As regras ficam em Empresa &gt; Configurações.</span></span>
          </label>
        </div>
      )}
      {user && f.tracks_time && String(user.schedule_id ?? "") !== f.schedule_id && (
        <p className="alert info small">O espelho desta pessoa passa a ser calculado com a nova jornada. Se houver mês fechado com marcações dela, a troca é recusada.</p>
      )}

      <p className="section-title" style={{ marginTop: 12 }}>Acesso</p>
      <label className="check">
        <input type="checkbox" checked={f.app_access} disabled={mustLogin} onChange={(e) => set({ app_access: e.target.checked })} />
        <span>Entra no aplicativo
          <span className="muted small" style={{ display: "block", fontWeight: 400 }}>
            {mustLogin ? "Obrigatório para quem tem função de gestão ou não registra ponto." : "Desmarque para quem só bate ponto na Central (não precisa de e-mail nem senha)."}
          </span>
        </span>
      </label>
      {f.app_access && (
        <div className="grid2">
          <label>E-mail (para entrar)<input type="email" required value={f.email} onChange={(e) => set({ email: e.target.value })} /></label>
          {!user && <label>Senha inicial<input type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={(e) => set({ password: e.target.value })} /></label>}
        </div>
      )}
      {!user && f.app_access && <p className="muted small" style={{ marginTop: 0 }}>A senha inicial é temporária: a pessoa cria a dela no primeiro acesso.</p>}
      {admin && (
        <fieldset style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "8px 12px", margin: "8px 0" }}>
          <legend className="small">Funções de gestão (opcional; marque quantas quiser)</legend>
          {FUNCS.map(([r, help]) => (
            <label key={r} className="check" style={{ margin: "4px 0" }}>
              <input type="checkbox" checked={f.roles.includes(r)} onChange={() => toggleRole(r)} />
              <span><b>{ROLE_LABEL[r]}</b> <span className="muted small">— {help}</span></span>
            </label>
          ))}
        </fieldset>
      )}

      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary" disabled={busy}>{busy ? "Salvando…" : user ? "Salvar" : "Cadastrar"}</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancelar</button>}
      </div>
    </form>
  );
}

export default function People() {
  const { user, can } = useAuth();
  const manage = can("people.manage");
  const admin = can("people.permissions");
  const [users, setUsers] = useState<User[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [query, setQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null); // "<ação>-<id>": confirmação na própria tela
  const [editing, setEditing] = useState<number | null>(null);
  const [temp, setTemp] = useState<{ name: string; password: string } | null>(null);
  const [badges, setBadges] = useState<Record<number, { employee_code: string; has_pin: boolean }>>({});
  const n = useNotice();

  const load = useCallback(async () => {
    try {
      const [u, s] = await Promise.all([api<User[]>("/users"), api<Schedule[]>("/schedules")]);
      setUsers(u);
      setSchedules(s);
    } catch (e) {
      n.fail(e);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [load]);

  async function act(path: string, body: object | undefined, okText: string, method = "POST") {
    try {
      await api(path, { method, body });
      n.ok(okText);
      setConfirm(null);
      await load();
    } catch (err) {
      setConfirm(null);
      n.fail(err);
    }
  }

  async function loadBadge(id: number) {
    try {
      const b = await api<{ employee_code: string; has_pin: boolean }>(`/users/${id}/badge`);
      setBadges((m) => ({ ...m, [id]: b }));
    } catch {
      /* sem permissão, ou a pessoa não registra ponto: só não mostra */
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

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users.filter((u) => (showInactive || u.active) && (!q || u.name.toLowerCase().includes(q) || (u.email ?? "").toLowerCase().includes(q)));
  }, [users, query, showInactive]);
  const nameOf = (id: number | null) => users.find((u) => u.id === id)?.name;
  const scheduleName = (id: number | null) => schedules.find((s) => s.id === id)?.name;
  const br = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "—");

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

      {manage && (
        <details className="fold">
          <summary>Cadastrar uma pessoa</summary>
          <PersonForm people={users} schedules={schedules} onSaved={(t) => { n.ok(t); void load(); }} />
        </details>
      )}

      <label className="search">
        <span className="sr-only">Buscar pessoa</span>
        <input type="search" placeholder="Buscar por nome ou e-mail" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap", margin: "0 0 8px" }}>
        <span className="muted small">{shown.length} pessoa(s)</span>
        <span className="row" style={{ flex: "none", gap: 12 }}>
          {manage && <button className="link" style={{ minHeight: 32 }} onClick={() => download("/badges.pdf", "crachas.pdf").catch((e) => n.fail(e))}>Crachás de todos (PDF)</button>}
          <button className="link" style={{ minHeight: 32 }} onClick={() => setShowInactive(!showInactive)} aria-pressed={showInactive}>
            {showInactive ? "Ocultar inativos" : "Mostrar inativos"}
          </button>
        </span>
      </div>

      <section className="card" style={{ padding: "4px 16px" }}>
        {shown.length === 0 && <p className="muted">Ninguém encontrado.</p>}
        {shown.map((u) => {
          const editable = manage && (funcsOf(u).length === 0 || admin);
          const tracks = u.tracks_time !== false;
          const access = u.app_access !== false;
          const self = u.id === user?.id;
          return (
            <details className="day-row" key={u.id} onToggle={(e) => e.currentTarget.open && manage && tracks && void loadBadge(u.id)}>
              <summary>
                <span className="avatar" aria-hidden="true">{initials(u.name)}</span>
                <span className="day-main">
                  <strong>{u.name}</strong>
                  <span className="muted small">{u.job_title ? `${u.job_title} · ` : ""}{u.email ?? "só na Central"}</span>
                </span>
                <span className="day-num" style={{ alignItems: "flex-end", gap: 4 }}>
                  {funcsOf(u).map((r) => <span className="tag" key={r}>{ROLE_LABEL[r]}</span>)}
                  {!tracks && <span className="tag">Não bate ponto</span>}
                  {!u.active && <span className="tag falta">Inativo</span>}
                </span>
              </summary>
              <div className="day-body" style={{ paddingLeft: 0 }}>
                <dl className="receipt small" style={{ marginBottom: 8 }}>
                  <dt>CPF</dt><dd>{fmtCpf(u.cpf)}</dd>
                  {tracks && (
                    <>
                      <dt>Admissão</dt><dd>{br(u.admitted_at)}</dd>
                      <dt>Jornada</dt><dd>{scheduleName(u.schedule_id) ?? "Sem jornada"}</dd>
                      <dt>Gestor</dt><dd>{nameOf(u.manager_id) ?? "Nenhum"}</dd>
                      <dt>Bate ponto</dt><dd>{access && u.punch_policy !== "kiosk" ? "Aplicativo e Central" : "Só na Central"}</dd>
                      <dt>Banco de horas</dt><dd>{u.hour_bank_enabled ? "Usa" : "Não usa"}</dd>
                    </>
                  )}
                  <dt>Aplicativo</dt><dd>{access ? `Entra${u.totp_enabled ? " · 2FA ativo" : ""}` : "Não entra"}</dd>
                  {badges[u.id] && (
                    <>
                      <dt>Código (Central)</dt><dd><code>{badges[u.id].employee_code}</code></dd>
                      <dt>PIN da Central</dt><dd>{badges[u.id].has_pin ? "Definido" : "Não definido"}</dd>
                    </>
                  )}
                </dl>
                {editable && (
                  <>
                    <div className="row">
                      <button className="primary" onClick={() => setEditing(editing === u.id ? null : u.id)}>{editing === u.id ? "Fechar edição" : "Editar cadastro"}</button>
                      {tracks && <button onClick={() => download(`/users/${u.id}/badge.pdf`, `cracha-${u.id}.pdf`).catch((e) => n.fail(e))}>Crachá (PDF)</button>}
                      {tracks && badges[u.id]?.has_pin && <button onClick={() => setConfirm(`pin-${u.id}`)}>Zerar PIN</button>}
                      {tracks && <button onClick={() => setConfirm(`badge-${u.id}`)}>Regenerar crachá</button>}
                      {!self && access && <button onClick={() => setConfirm(`pw-${u.id}`)}>Nova senha</button>}
                      {!self && u.totp_enabled && <button onClick={() => setConfirm(`2fa-${u.id}`)}>Zerar 2FA</button>}
                      {!self && <button className={u.active ? "danger" : ""} onClick={() => setConfirm(`act-${u.id}`)}>{u.active ? "Desativar" : "Reativar"}</button>}
                      {!self && <button className="danger" onClick={() => setConfirm(`del-${u.id}`)}>Excluir</button>}
                    </div>
                    {editing === u.id && (
                      <PersonForm key={u.id} user={u} people={users} schedules={schedules}
                        onSaved={(t) => { n.ok(t); setEditing(null); void load(); }} onCancel={() => setEditing(null)} />
                    )}
                    <Confirm id={`del-${u.id}`} danger text={`Excluir o cadastro de ${u.name}? Só é possível se a pessoa nunca teve marcações, ajustes, ausências ou banco de horas (cadastro feito por engano). Não dá para desfazer. Quem já trabalhou deve ser desativado, para manter o histórico.`}
                      onYes={() => act(`/users/${u.id}`, undefined, `${u.name} excluída(o) do cadastro.`, "DELETE")} />
                    <Confirm id={`pin-${u.id}`} text={`Zerar o PIN de ${u.name}? Ela define outro em Minha conta.`} onYes={() => act(`/users/${u.id}/pin-reset`, undefined, "PIN zerado.").then(() => loadBadge(u.id))} />
                    <Confirm id={`badge-${u.id}`} danger text={`Regenerar o crachá de ${u.name}? O QR impresso atual deixa de funcionar na Central; imprima o novo.`}
                      onYes={() => act(`/users/${u.id}/badge/regenerate`, undefined, "Crachá regenerado: o impresso anterior não vale mais.")} />
                    <Confirm id={`pw-${u.id}`} text={`Gerar uma senha temporária para ${u.name}? A senha atual deixa de valer e as sessões abertas caem.`} onYes={() => resetPassword(u)} />
                    <Confirm id={`2fa-${u.id}`} text={`Remover a verificação em duas etapas de ${u.name}? Use só se ela perdeu o celular e os códigos de recuperação.`}
                      onYes={() => act(`/users/${u.id}/reset-2fa`, undefined, "2FA removido. A pessoa poderá configurá-lo de novo em Minha conta.")} />
                    <Confirm id={`act-${u.id}`} danger={u.active} text={u.active ? `Desativar ${u.name}? A pessoa não consegue mais entrar nem bater ponto; o histórico é mantido.` : `Reativar ${u.name}?`}
                      onYes={() => act(`/users/${u.id}`, { active: !u.active }, u.active ? "Pessoa desativada." : "Pessoa reativada.", "PATCH")} />
                  </>
                )}
                {manage && !editable && <p className="muted small">Só a Administração altera quem tem função de gestão.</p>}
              </div>
            </details>
          );
        })}
      </section>

      {manage && (
        <details className="fold">
          <summary>Importar várias pessoas por CSV</summary>
          <ImportCard onDone={load} />
        </details>
      )}
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

