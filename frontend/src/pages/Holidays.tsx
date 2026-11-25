import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";

interface Row { date: string; name: string; source: "nacional" | "opcional" | "empresa"; id: number | null; recurring?: boolean }
interface Cal { year: number; carnaval: boolean; corpus_christi: boolean; holidays: Row[] }

const SOURCE: Record<Row["source"], string> = { nacional: "Nacional", opcional: "Facultativo", empresa: "Da empresa" };
// Sugestões para quem está em Salvador/BA: confirme no calendário oficial do estado e da prefeitura antes de cadastrar.
const SUGGESTIONS: { label: string; items: { md: string; name: string }[] }[] = [
  { label: "Bahia (estadual)", items: [{ md: "07-02", name: "Independência da Bahia" }] },
  { label: "Salvador (municipal)", items: [{ md: "06-24", name: "São João" }, { md: "12-08", name: "Nossa Senhora da Conceição da Praia" }] },
];
const br = (iso: string) => iso.split("-").reverse().join("/");
const weekday = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("pt-BR", { weekday: "long", timeZone: "UTC" });

/** Empresa > Configurações > Feriados: nacionais automáticos, Carnaval e Corpus Christi opcionais, estaduais e municipais. */
export default function Holidays() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [cal, setCal] = useState<Cal | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [f, setF] = useState({ date: "", name: "", recurring: true });

  const load = useCallback(() => api<Cal>(`/holidays?year=${year}`).then(setCal).catch((e) => setMsg({ type: "error", text: e.message })), [year]);
  useEffect(() => { void load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      setMsg({ type: "ok", text: ok });
      await load();
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  const add = (date: string, name: string, recurring: boolean) =>
    run(() => api("/holidays", { method: "POST", body: { date, name, recurring } }), `${name} cadastrado.`);

  function submit(e: FormEvent) {
    e.preventDefault();
    void add(f.date, f.name.trim(), f.recurring).then(() => setF({ date: "", name: "", recurring: true }));
  }

  const taken = new Set((cal?.holidays ?? []).map((h) => h.date.slice(5)));

  return (
    <section className="card" aria-labelledby="h-feriados">
      <h2 id="h-feriados" className="section-title">Feriados</h2>
      <p className="muted small">
        Num feriado ninguém leva falta, e o que for trabalhado conta como hora extra. Os nacionais já estão incluídos e são
        calculados a cada ano (inclusive a Sexta-feira Santa). Cadastre aqui os estaduais e municipais.
      </p>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      <label className="check">
        <input type="checkbox" checked={!!cal?.carnaval} onChange={(e) => run(() => api("/holidays/options", { method: "PATCH", body: { carnaval: e.target.checked } }),
          e.target.checked ? "Carnaval passa a ser folga." : "Carnaval volta a ser dia normal.")} />
        <span>Folgar no Carnaval (segunda e terça)</span>
      </label>
      <label className="check">
        <input type="checkbox" checked={!!cal?.corpus_christi} onChange={(e) => run(() => api("/holidays/options", { method: "PATCH", body: { corpus_christi: e.target.checked } }),
          e.target.checked ? "Corpus Christi passa a ser folga." : "Corpus Christi volta a ser dia normal.")} />
        <span>Folgar em Corpus Christi</span>
      </label>

      <div className="month-nav" style={{ margin: "12px 0" }}>
        <button className="icon-btn" onClick={() => setYear(year - 1)} aria-label="Ano anterior">‹</button>
        <strong className="month-title" aria-live="polite">{year}</strong>
        <button className="icon-btn" onClick={() => setYear(year + 1)} aria-label="Próximo ano">›</button>
      </div>
      <ul className="plain">
        {(cal?.holidays ?? []).map((h) => (
          <li key={`${h.date}-${h.name}`}>
            <span>
              <b>{br(h.date)}</b> <span className="muted small">{weekday(h.date)}</span> · {h.name}
              <span className="tag" style={{ marginLeft: 6 }}>{SOURCE[h.source]}{h.source === "empresa" && !h.recurring ? " (só este ano)" : ""}</span>
            </span>
            {h.id && <button className="link" style={{ minHeight: 32 }} onClick={() => run(() => api(`/holidays/${h.id}`, { method: "DELETE" }), `${h.name} removido.`)}>Remover</button>}
          </li>
        ))}
      </ul>

      <details className="fold">
        <summary>Cadastrar feriado estadual ou municipal</summary>
        {SUGGESTIONS.map((g) => (
          <div key={g.label} style={{ marginBottom: 8 }}>
            <span className="muted small">{g.label}: </span>
            {g.items.map((it) => (
              <button key={it.md} type="button" className="fchip" disabled={taken.has(it.md)} onClick={() => add(`${year}-${it.md}`, it.name, true)}>
                {br(`${year}-${it.md}`).slice(0, 5)} {it.name}{taken.has(it.md) ? " ✓" : ""}
              </button>
            ))}
          </div>
        ))}
        <p className="muted small">Sugestões para Salvador/BA: confirme no calendário oficial do estado e da prefeitura antes de cadastrar.</p>
        <form onSubmit={submit}>
          <div className="grid2 keep">
            <label>Data<input type="date" required value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
            <label>Nome<input required minLength={2} maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          </div>
          <label className="check">
            <input type="checkbox" checked={f.recurring} onChange={(e) => setF({ ...f, recurring: e.target.checked })} />
            <span>Repete todo ano nesta data</span>
          </label>
          <button className="primary">Cadastrar</button>
        </form>
      </details>
    </section>
  );
}
