import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../google";
import type { OvertimeRule } from "../types";
import Holidays from "./Holidays";

type Notice = { type: "ok" | "error"; text: string } | null;

/** Gestão > Empresa > Configurações (só a Administração): dados da empresa e regras que valem para todos. */
export default function Settings() {
  const { company, reload, user } = useAuth();
  const config = useConfig();
  const [msg, setMsg] = useState<Notice>(null);
  const c = company!;

  async function save(body: object, okText: string) {
    try {
      await api("/company", { method: "PATCH", body });
      await reload();
      setMsg({ type: "ok", text: okText });
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    }
  }

  return (
    <>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      <CompanyData onSave={save} />
      <Holidays />
      <BankRules onSave={save} />
      <OvertimeRules onSave={save} />

      <section className="card" aria-labelledby="h-foto">
        <h2 id="h-foto" className="section-title">Foto na batida</h2>
        <p className="muted small">
          Opcional no aplicativo. Cada pessoa autoriza a própria foto (LGPD); se a câmera falhar ou a pessoa recusar, o ponto é registrado do
          mesmo jeito. As fotos são criptografadas, só o RH e a Administração as veem e <b>são apagadas quando o mês é fechado</b>.
        </p>
        <label className="check">
          <input type="checkbox" checked={!!c.photo_enabled}
            onChange={(e) => save({ photo_enabled: e.target.checked }, e.target.checked ? "Foto na batida ativada." : "Foto na batida desativada (as já tiradas seguem até o fechamento do mês).")} />
          <span>Permitir foto na batida pelo aplicativo</span>
        </label>
      </section>

      {config?.google_client_id && (
        <section className="card" aria-labelledby="h-login">
          <h2 id="h-login" className="section-title">Login</h2>
          <p className="muted small">
            Todos podem usar “Entrar com Google” (com a conta do e-mail cadastrado, ou vinculando outra em Minha conta).
            Desligue a senha para aceitar só o Google; quem ainda não tem conta Google continua sem acesso até vincular uma.
          </p>
          <label className="check">
            <input type="checkbox" checked={c.password_login !== false}
              onChange={(e) => save({ password_login: e.target.checked }, e.target.checked ? "Login com e-mail e senha permitido." : "Agora só se entra com o Google.")} />
            <span>Permitir também entrar com e-mail e senha</span>
          </label>
          {c.password_login !== false && !user?.google_linked && (
            <p className="muted small" style={{ margin: "8px 0 0" }}>Para poder desligar a senha, vincule antes a sua conta Google em Minha conta.</p>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="h-pin">
        <h2 id="h-pin" className="section-title">Central do Ponto</h2>
        <label className="check">
          <input type="checkbox" checked={!!c.kiosk_pin_required}
            onChange={(e) => save({ kiosk_pin_required: e.target.checked }, e.target.checked ? "A Central passa a pedir o PIN." : "A Central não pede mais o PIN.")} />
          <span>
            Exigir PIN na Central
            <span className="muted small" style={{ display: "block", fontWeight: 400 }}>
              Desligado (padrão): o código interno ou o CPF sozinho identifica a pessoa, então trate o código como uma senha. Ligado: a pessoa também
              digita o PIN que definiu em Minha conta. O QR do aplicativo, que muda a cada 30 segundos, dispensa o PIN.
            </span>
          </span>
        </label>
        <p className="muted small" style={{ margin: "8px 0 0" }}>A foto é sempre obrigatória na Central. Os aparelhos ficam em Cadastros &gt; Centrais.</p>
      </section>
    </>
  );
}

function CompanyData({ onSave }: { onSave: (body: object, ok: string) => Promise<void> }) {
  const { company } = useAuth();
  const c = company!;
  const [f, setF] = useState({ name: c.name, workplace: c.workplace ?? "", caepf: c.caepf ?? "", cno: c.cno ?? "", timezone: c.timezone });

  function submit(e: FormEvent) {
    e.preventDefault();
    void onSave({ name: f.name.trim(), workplace: f.workplace.trim() || null, caepf: f.caepf.trim() || null, cno: f.cno.trim() || null, timezone: f.timezone },
      "Dados da empresa salvos.");
  }

  return (
    <form className="card" onSubmit={submit} aria-labelledby="h-empresa">
      <h2 id="h-empresa" className="section-title">Empresa</h2>
      <label>Razão social<input required minLength={2} maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>CNPJ<input value={c.cnpj} disabled /></label>
      <p className="muted small" style={{ marginTop: -6 }}>O CNPJ identifica o estabelecimento nos registros do REP-P e não muda por aqui.</p>
      <label>Local de prestação do serviço<input maxLength={300} placeholder="Endereço do estabelecimento" value={f.workplace} onChange={(e) => setF({ ...f, workplace: e.target.value })} /></label>
      <div className="grid2 keep">
        <label>CAEPF (se houver)<input inputMode="numeric" maxLength={14} value={f.caepf} onChange={(e) => setF({ ...f, caepf: e.target.value })} /></label>
        <label>CNO (se houver)<input inputMode="numeric" maxLength={14} value={f.cno} onChange={(e) => setF({ ...f, cno: e.target.value })} /></label>
      </div>
      <label>Fuso horário
        <select value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>
          {["America/Sao_Paulo", "America/Bahia", "America/Fortaleza", "America/Recife", "America/Belem", "America/Manaus", "America/Cuiaba",
            "America/Campo_Grande", "America/Porto_Velho", "America/Boa_Vista", "America/Rio_Branco", "America/Noronha"].map((z) => <option key={z}>{z}</option>)}
        </select>
      </label>
      <p className="muted small">Mudanças nos dados do empregador ficam registradas no REP-P (registro tipo 2) e na auditoria.</p>
      <button className="primary">Salvar dados da empresa</button>
    </form>
  );
}

function BankRules({ onSave }: { onSave: (body: object, ok: string) => Promise<void> }) {
  const { company } = useAuth();
  const [limit, setLimit] = useState(company?.bank_max_minutes != null ? String(company.bank_max_minutes / 60) : "");
  const [months, setMonths] = useState(String(company?.bank_expiry_months ?? 6));

  function submit(e: FormEvent) {
    e.preventDefault();
    void onSave({ bank_max_minutes: limit === "" ? null : Math.round(Number(limit) * 60), bank_expiry_months: Number(months) }, "Regras do banco de horas salvas.");
  }

  return (
    <form className="card" onSubmit={submit} aria-labelledby="h-banco">
      <h2 id="h-banco" className="section-title">Banco de horas</h2>
      <div className="grid2 keep">
        <label>Limite do saldo (horas; vazio = sem)<input type="number" min="0" step="0.5" value={limit} onChange={(e) => setLimit(e.target.value)} /></label>
        <label>Prazo para compensar (meses)<input type="number" min="1" max="12" value={months} onChange={(e) => setMonths(e.target.value)} /></label>
      </div>
      <p className="muted small">O prazo depende do instrumento adotado (acordo individual ou coletivo); confirme com a assessoria jurídica. Quem usa banco de horas é definido no cadastro de cada pessoa.</p>
      <button>Salvar regras</button>
    </form>
  );
}

const DAY_TYPES: [keyof OvertimeRule, string][] = [["util", "Dias úteis"], ["sabado", "Sábados"], ["domingo", "Domingos"], ["feriado", "Feriados"]];
type Row = { first: string; after: string; excess: string };

function OvertimeRules({ onSave }: { onSave: (body: object, ok: string) => Promise<void> }) {
  const { company } = useAuth();
  const rule = company?.overtime_rule;
  const [rows, setRows] = useState<Record<string, Row>>(() => Object.fromEntries(DAY_TYPES.map(([t]) => {
    const b = rule?.[t] ?? { limit: null, first: t === "domingo" || t === "feriado" ? 100 : 50, excess: 100 };
    return [t, { first: String(b.first), after: b.limit == null || b.first === b.excess ? "" : String(b.limit / 60), excess: String(b.excess) }];
  })));
  const set = (t: string, k: keyof Row, v: string) => setRows((r) => ({ ...r, [t]: { ...r[t], [k]: v } }));

  function submit(e: FormEvent) {
    e.preventDefault();
    const body = Object.fromEntries(DAY_TYPES.map(([t]) => {
      const r = rows[t];
      const split = r.after !== "";
      return [t, { limit: split ? Math.round(Number(r.after) * 60) : null, first: Number(r.first), excess: split ? Number(r.excess) : Number(r.first) }];
    }));
    void onSave({ overtime_rule: body }, "Faixas de horas extras salvas.");
  }

  return (
    <form className="card" onSubmit={submit} aria-labelledby="h-extras">
      <h2 id="h-extras" className="section-title">Horas extras pagas</h2>
      <p className="muted small">
        Para quem <b>não</b> usa banco de horas: o saldo positivo de cada dia é pago com o percentual do tipo de dia. Para mudar o percentual
        a partir de certa quantidade de horas extras no mesmo dia (ex.: 2 primeiras a 50 %, o resto a 100 %), preencha “Depois de”.
      </p>
      {DAY_TYPES.map(([t, label]) => (
        <fieldset key={t} style={{ border: 0, padding: 0, margin: "0 0 4px" }}>
          <legend style={{ fontWeight: 600, fontSize: ".92rem", marginBottom: 4 }}>{label}</legend>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0 10px" }}>
            <label>Percentual (%)<input type="number" min="50" max="300" required value={rows[t].first} onChange={(e) => set(t, "first", e.target.value)} /></label>
            <label>Depois de (horas)<input type="number" min="0" max="24" step="0.5" placeholder="não muda" value={rows[t].after}
              onChange={(e) => set(t, "after", e.target.value)} /></label>
            <label>Passa a (%)<input type="number" min="50" max="300" disabled={rows[t].after === ""} required={rows[t].after !== ""}
              value={rows[t].after === "" ? "" : rows[t].excess} onChange={(e) => set(t, "excess", e.target.value)} /></label>
          </div>
        </fieldset>
      ))}
      <p className="muted small">
        Padrão: 50 % em dias úteis e sábados, 100 % em domingos e feriados (CLT art. 59 e Súmula 146 do TST); confira a convenção coletiva.
        A regra vale para todo cálculo feito a partir de agora, inclusive de meses anteriores: mude no início de uma competência.
        Os minutos noturnos (adicional noturno) seguem à parte, no relatório.
      </p>
      <button>Salvar faixas</button>
    </form>
  );
}
