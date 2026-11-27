import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { currentMonth, fmtMonth, shiftMonth } from "../util";

/** Gestão > Folha de pagamento: os eventos do mês (horas extras por percentual, adicional noturno, faltas, DSR perdido,
 * atrasos) com o código da verba e a matrícula de cada pessoa, no arquivo da Domínio, da Alterdata ou em CSV. */

type System = "dominio" | "alterdata" | "csv";
interface Event { key: string; label: string; unit: "horas" | "dias" }
interface Config { system: System; company_code: string; process: string; codes: Record<string, string> }
interface ConfigData {
  config: Config; events: Event[]; systems: Record<System, string>; processes: Record<System, Record<string, string>>;
  limits: Record<System, { company: number; employee: number; event: number }>;
}
interface Row { user_id: number; name: string; job_title: string; payroll_code: string | null; hour_bank: boolean; active: boolean; values: Record<string, number> }
interface Preview {
  month: string; closed: boolean; config: Config; events: Event[]; rows: Row[]; totals: Record<string, number>;
  pending: { company_code: boolean; people_without_code: string[]; events_without_code: string[]; incomplete_days: string[] };
}

export function fmtAmount(value: number | undefined, unit: Event["unit"]): string {
  if (!value) return "";
  if (unit === "dias") return String(value);
  const minutes = Math.round(value * 60);
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

const digits = (v: string) => v.replace(/\D/g, "");

export default function Payroll() {
  const { company } = useAuth();
  const tz = company!.timezone;
  const [month, setMonth] = useState(() => shiftMonth(currentMonth(tz), -1)); // a folha costuma ser do mês que acabou
  const [cfg, setCfg] = useState<ConfigData | null>(null);
  const [form, setForm] = useState<Config | null>(null);
  const [data, setData] = useState<Preview | null>(null);
  const [codes, setCodes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [editConfig, setEditConfig] = useState(false);

  const loadConfig = useCallback(async () => {
    const c = await api<ConfigData>("/payroll/config");
    setCfg(c);
    setForm(c.config);
    return c;
  }, []);
  const load = useCallback(async () => {
    setBusy("load");
    try {
      const p = await api<Preview>(`/payroll/preview?month=${month}`);
      setData(p);
      setCodes(Object.fromEntries(p.rows.map((r) => [r.user_id, r.payroll_code ?? ""])));
    } catch (e) {
      setData(null);
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao calcular o mês" });
    } finally {
      setBusy("");
    }
  }, [month]);
  useEffect(() => {
    loadConfig().then((c) => { if (!c.config.codes || !Object.keys(c.config.codes).length) setEditConfig(true); })
      .catch((e) => setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" }));
  }, [loadConfig]);
  useEffect(() => { void load(); }, [load]);

  const rows = data?.rows ?? [];
  const withValues = rows.filter((r) => Object.keys(r.values).length);
  const changedCodes = useMemo(
    () => rows.filter((r) => (codes[r.user_id] ?? "") !== (r.payroll_code ?? "")).map((r) => ({ user_id: r.user_id, code: codes[r.user_id] || null })),
    [rows, codes],
  );
  const system = data?.config.system ?? "csv";

  async function saveConfig(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy("config");
    setMsg(null);
    try {
      await api("/payroll/config", { method: "PUT", body: form });
      await loadConfig();
      await load();
      setEditConfig(false);
      setMsg({ type: "ok", text: "Verbas salvas." });
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro ao salvar" });
    } finally {
      setBusy("");
    }
  }

  async function saveCodes() {
    setBusy("codes");
    setMsg(null);
    try {
      const r = await api<{ changed: number }>("/payroll/codes", { method: "PUT", body: { items: changedCodes } });
      await load();
      setMsg({ type: "ok", text: `${r.changed} matrícula(s) salva(s).` });
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro ao salvar" });
    } finally {
      setBusy("");
    }
  }

  async function get(format: System) {
    setBusy(format);
    setMsg(null);
    const name = `folha-${format}-${month}.${format === "csv" ? "csv" : "txt"}`;
    try {
      await download(`/payroll/export?month=${month}&format=${format}`, name);
      setMsg({ type: "ok", text: `${name} gerado. Confira a pasta de downloads.` });
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro ao gerar o arquivo" });
    } finally {
      setBusy("");
    }
  }

  const p = data?.pending;
  const hasPending = !!p && (p.company_code || p.people_without_code.length > 0 || p.events_without_code.length > 0);
  const limits = form && cfg ? cfg.limits[form.system] : null;

  return (
    <>
      <h1>Folha de pagamento</h1>
      <p className="muted small" style={{ marginTop: -6 }}>
        Os eventos do mês de cada pessoa, calculados do espelho, no arquivo de importação do seu sistema de folha: horas extras por
        percentual, adicional noturno, faltas, DSR perdido e atrasos. Cada arquivo gerado fica na auditoria.
      </p>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      {cfg && form && (editConfig ? (
        <form className="card" onSubmit={saveConfig} aria-labelledby="h-verbas">
          <h2 id="h-verbas" className="section-title">Sistema de folha e verbas</h2>
          <div className="grid2 keep">
            <label>Sistema de folha
              <select value={form.system} onChange={(e) => {
                const s = e.target.value as System;
                setForm({ ...form, system: s, process: Object.keys(cfg.processes[s])[0] ?? "" });
              }}>
                {(Object.keys(cfg.systems) as System[]).map((s) => <option key={s} value={s}>{cfg.systems[s]}</option>)}
              </select>
            </label>
            {form.system !== "csv" && (
              <label>Código da empresa no sistema
                <input inputMode="numeric" required maxLength={limits?.company} value={form.company_code}
                  onChange={(e) => setForm({ ...form, company_code: digits(e.target.value) })} />
              </label>
            )}
          </div>
          {form.system !== "csv" && (
            <label>Tipo de processo
              <select value={form.process} onChange={(e) => setForm({ ...form, process: e.target.value })}>
                {Object.entries(cfg.processes[form.system]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          )}
          <p className="muted small">
            Código de cada verba no sistema de folha (só números{limits ? `, até ${limits.event} dígitos` : ""}). Verba sem código não vai
            para o arquivo. Horas vão em horas centesimais (10h30 = 10,50) e faltas e DSR em dias.
          </p>
          <div className="grid2 keep">
            {cfg.events.map((ev) => (
              <label key={ev.key}>{ev.label}
                <input inputMode="numeric" maxLength={limits?.event} value={form.codes[ev.key] ?? ""} placeholder="sem código"
                  onChange={(e) => setForm({ ...form, codes: { ...form.codes, [ev.key]: digits(e.target.value) } })} />
              </label>
            ))}
          </div>
          {form.system === "dominio" && (
            <p className="muted small">
              Leiaute “Importação Arquivo Texto | De Lançamentos” da Domínio. As datas de cada falta e do DSR perdido vão logo abaixo da
              verba de faltas. Na Domínio: Utilitários &gt; Importação &gt; De Arquivo Texto &gt; de Lançamentos.
            </p>
          )}
          {form.system === "alterdata" && (
            <p className="muted small">
              Arquivo de movimento da Alterdata. Na Alterdata: Folha &gt; Lançamento por Funcionário &gt; Importar. O PIS vai zerado e a pessoa
              é identificada pela matrícula.
            </p>
          )}
          <p className="muted small">Faça a primeira importação num mês de teste e confira com o seu escritório contábil.</p>
          <div className="row">
            <button className="primary" disabled={busy === "config"}>{busy === "config" ? "Salvando…" : "Salvar verbas"}</button>
            {Object.keys(cfg.config.codes).length > 0 && <button type="button" onClick={() => { setForm(cfg.config); setEditConfig(false); }}>Cancelar</button>}
          </div>
        </form>
      ) : (
        <section className="card" aria-labelledby="h-verbas">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 id="h-verbas" className="section-title" style={{ margin: 0 }}>{cfg.systems[cfg.config.system]}</h2>
            <button style={{ flex: "0 0 auto" }} onClick={() => setEditConfig(true)}>Editar verbas</button>
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>
            {cfg.config.system !== "csv" && <>Empresa {cfg.config.company_code || "sem código"} · processo {cfg.config.process} · </>}
            {cfg.events.filter((e) => cfg.config.codes[e.key]).map((e) => `${e.label}: ${cfg.config.codes[e.key]}`).join(" · ") || "Nenhuma verba com código."}
          </p>
        </section>
      ))}

      <div className="month-nav" style={{ margin: "4px 0 12px" }}>
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Mês anterior">‹</button>
        <strong className="month-title" aria-live="polite">{fmtMonth(month)}</strong>
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Próximo mês" disabled={month >= currentMonth(tz)}>›</button>
      </div>

      {data && !data.closed && (
        <p className="alert warn" role="status">Este mês ainda não está fechado: o ponto ainda pode mudar. Feche em Empresa &gt; Fechamento antes de enviar à folha.</p>
      )}
      {p && p.incomplete_days.length > 0 && (
        <p className="alert warn" role="status">Dias com marcação incompleta (corrija no Tratamento): {p.incomplete_days.join(", ")}.</p>
      )}
      {hasPending && (
        <div className="alert warn" role="status">
          <b>Fica de fora do arquivo:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {p!.company_code && <li>tudo, até informar o código da empresa no sistema de folha;</li>}
            {p!.events_without_code.length > 0 && <li>verbas sem código: {p!.events_without_code.join(", ")};</li>}
            {p!.people_without_code.length > 0 && <li>pessoas sem matrícula: {p!.people_without_code.join(", ")}.</li>}
          </ul>
        </div>
      )}

      {busy === "load" && !data && <p className="muted" role="status">Calculando o mês…</p>}
      {data && (
        <section className="card" aria-label="Eventos do mês">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Pessoa</th>
                  <th style={{ textAlign: "left" }}>Matrícula</th>
                  {data.events.map((e) => <th key={e.key} title={data.config.codes[e.key] ? `Verba ${data.config.codes[e.key]}` : "Sem código"}>{e.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user_id}>
                    <td>
                      {r.name}
                      {r.hour_bank && <span className="muted small"> · banco de horas</span>}
                      {!r.active && <span className="muted small"> · desligado</span>}
                    </td>
                    <td>
                      <input aria-label={`Matrícula de ${r.name}`} inputMode="numeric" style={{ width: "7em", margin: 0 }}
                        maxLength={cfg?.limits[system].employee} value={codes[r.user_id] ?? ""}
                        onChange={(e) => setCodes({ ...codes, [r.user_id]: digits(e.target.value) })} />
                    </td>
                    {data.events.map((e) => <td key={e.key} style={{ textAlign: "right" }}>{fmtAmount(r.values[e.key], e.unit)}</td>)}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th style={{ textAlign: "left" }} colSpan={2}>Total</th>
                  {data.events.map((e) => <th key={e.key} style={{ textAlign: "right" }}>{fmtAmount(data.totals[e.key], e.unit)}</th>)}
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="muted small">
            Quem usa banco de horas não tem horas extras nem atrasos aqui: o saldo do dia vai para o banco. O DSR perdido é o domingo da
            semana com falta sem justificativa.
          </p>
          <div className="row">
            <button disabled={!changedCodes.length || busy === "codes"} onClick={saveCodes}>
              {busy === "codes" ? "Salvando…" : `Salvar matrículas${changedCodes.length ? ` (${changedCodes.length})` : ""}`}
            </button>
          </div>
        </section>
      )}

      {data && (
        <section className="card" aria-labelledby="h-arquivo">
          <h2 id="h-arquivo" className="section-title">Arquivo para a folha</h2>
          <p className="muted small">{withValues.length} pessoa(s) com eventos em {fmtMonth(month).toLowerCase()}.</p>
          {changedCodes.length > 0 && <p className="alert warn">Salve as matrículas antes de gerar o arquivo.</p>}
          <div className="row">
            {system !== "csv" && (
              <button className="primary" disabled={!!busy || changedCodes.length > 0 || !withValues.length} onClick={() => get(system)}>
                {busy === system ? "Gerando…" : `Baixar arquivo ${system === "dominio" ? "da Domínio" : "da Alterdata"} (TXT)`}
              </button>
            )}
            <button className={system === "csv" ? "primary" : ""} disabled={!!busy || changedCodes.length > 0 || !withValues.length} onClick={() => get("csv")}>
              {busy === "csv" ? "Gerando…" : "Baixar planilha (CSV)"}
            </button>
          </div>
        </section>
      )}
    </>
  );
}
