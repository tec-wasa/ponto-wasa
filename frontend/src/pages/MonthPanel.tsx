import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { MonthOverview, MonthPerson } from "../types";
import { currentMonth, fmtMinutes, fmtMonth, shiftMonth, todayLocal } from "../util";

// Cores validadas para daltonismo (claro e escuro) em styles.css: --chart-ok, --chart-warn, --chart-bad.
const SERIES = [
  { key: "ok", label: "Dia completo", color: "var(--chart-ok)" },
  { key: "incompleto", label: "Saída não registrada", color: "var(--chart-warn)" },
  { key: "falta", label: "Falta", color: "var(--chart-bad)" },
] as const;

const signed = (m: number) => `${m > 0 ? "+" : ""}${fmtMinutes(m)}`;

/** Painel > indicadores do mês: números do mês, situação dia a dia e quem precisa de atenção. */
export default function MonthPanel() {
  const { company, can } = useAuth();
  const tz = company!.timezone;
  const now = currentMonth(tz);
  const [month, setMonth] = useState(now);
  const [data, setData] = useState<MonthOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setError("");
    api<MonthOverview>(`/dashboard/month?month=${month}`)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : "Erro ao carregar os indicadores"); });
    return () => { alive = false; };
  }, [month]);

  const ready = data && data.month === month ? data : null;
  const t = ready?.totals;
  const pending = ready ? ready.pending.adjustments + ready.pending.absences : 0;
  const treat = can("approvals") ? `/gestao/tratamento?mes=${month}` : undefined;

  return (
    <section className="month-panel" aria-labelledby="h-mes">
      <div className="dash-head">
        <h2 id="h-mes">Indicadores do mês</h2>
        <div className="month-nav">
          <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Mês anterior">‹</button>
          <strong className="month-title" aria-live="polite">
            {fmtMonth(month)}{ready?.closed && <span className="tag" style={{ marginLeft: 6 }}>Fechado</span>}
          </strong>
          <button className="icon-btn" disabled={month >= now} onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Próximo mês">›</button>
        </div>
      </div>
      {error && <p className="alert error" role="alert">{error}</p>}
      {!ready && !error && <p className="muted">Calculando o mês…</p>}

      {ready && t && (
        <>
          <div className="kpis">
            <Kpi label="Horas trabalhadas" value={fmtMinutes(t.worked)} sub={`de ${fmtMinutes(t.expected)} previstas até hoje`} />
            <Kpi label="Horas extras" value={signed(t.extra)} sub={t.debit ? `débitos ${fmtMinutes(t.debit)}` : "sem débitos"} />
            <Kpi label="Faltas" value={String(t.absences)} sub={t.justified ? `${t.justified} dia(s) justificado(s)` : "dias sem marcação"}
              alert={t.absences > 0} to={treat} />
            <Kpi label="Atrasos" value={String(t.late_days)} sub="dias com entrada após a tolerância" />
            <Kpi label="A tratar" value={String(t.incomplete)} sub="dias com saída não registrada" alert={t.incomplete > 0} to={treat} />
            {can("approvals") && (
              <Kpi label="Aprovações" value={String(pending)} sub={`${ready.pending.adjustments} ajuste(s) · ${ready.pending.absences} ausência(s)`}
                alert={pending > 0} to="/gestao/aprovacoes" />
            )}
            {ready.bank.people > 0 && (
              <Kpi label="Banco de horas" value={signed(ready.bank.balance)}
                sub={ready.bank.alerts ? `${ready.bank.alerts} pessoa(s) com alerta` : `${ready.bank.people} pessoa(s), sem alertas`}
                alert={ready.bank.alerts > 0} to="/gestao/banco" />
            )}
          </div>

          {ready.people_count === 0 ? (
            <p className="card muted">Ninguém para acompanhar neste mês.</p>
          ) : (
            <div className="dash-grid">
              <DaysChart data={ready} today={todayLocal(tz)} />
              <PeopleRank data={ready} treat={treat} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Kpi({ label, value, sub, alert, to }: { label: string; value: string; sub: string; alert?: boolean; to?: string }) {
  const body = (
    <>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      <span className="kpi-sub">{sub}</span>
    </>
  );
  const cls = `kpi${alert ? " attn-kpi" : ""}`;
  return to ? <Link to={to} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Retângulo com só os cantos de cima arredondados (a ponta do dado; a base fica reta, presa ao eixo). */
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function DaysChart({ data, today }: { data: MonthOverview; today: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [y, m] = data.month.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const byDate = new Map(data.days.map((d) => [Number(d.date.slice(8)), d]));
  const max = Math.max(1, data.people_count);
  const H = 180, top = 10, bottom = 22, left = 26;
  const plotH = H - top - bottom;
  const band = Math.max(1, (width - left) / last);
  const barW = Math.max(3, Math.min(18, band - 3));
  const sy = (v: number) => (v / max) * plotH;
  const ticks = max <= 4 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  const h = hover != null ? byDate.get(hover) : undefined;

  return (
    <section className="card" aria-labelledby="h-dias">
      <h3 id="h-dias" className="section-title" style={{ margin: 0 }}>Situação dos dias</h3>
      <p className="muted small" style={{ margin: "2px 0 0" }}>Quantas pessoas em cada situação, dia a dia. Folgas, feriados e dias futuros ficam em branco.</p>
      <div className="legend" aria-hidden="true">
        {SERIES.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <div className="chart-wrap" ref={ref} onMouseLeave={() => setHover(null)}>
        <svg width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img"
          aria-label={`Situação dos dias de ${fmtMonth(data.month)}; a tabela abaixo traz os números`}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={left} x2={width} y1={top + plotH - sy(v)} y2={top + plotH - sy(v)} stroke="var(--chart-grid)" />
              <text className="tick" x={left - 6} y={top + plotH - sy(v) + 3} textAnchor="end">{v}</text>
            </g>
          ))}
          {Array.from({ length: last }, (_, i) => i + 1).map((day) => {
            const d = byDate.get(day);
            const x = left + (day - 1) * band + (band - barW) / 2;
            let base = top + plotH;
            const segs = d ? SERIES.filter((s) => d[s.key] > 0) : [];
            return (
              <g key={day}>
                {hover === day && <rect x={left + (day - 1) * band} y={top} width={band} height={plotH} fill="var(--chart-grid)" />}
                {segs.map((s, i) => {
                  const hh = sy(d![s.key]);
                  const gap = i > 0 ? 2 : 0; // 2px de fundo entre os segmentos
                  base -= hh;
                  const hgt = Math.max(1, hh - gap);
                  return i === segs.length - 1
                    ? <path key={s.key} d={topRounded(x, base + gap, barW, hgt, 4)} fill={s.color} />
                    : <rect key={s.key} x={x} y={base + gap} width={barW} height={hgt} fill={s.color} />;
                })}
                {(day === 1 || day % 5 === 0) && (
                  <text className="tick" x={left + (day - 0.5) * band} y={H - 6} textAnchor="middle">{day}</text>
                )}
                <rect x={left + (day - 1) * band} y={0} width={band} height={H} fill="transparent"
                  onMouseEnter={() => setHover(day)} onClick={() => setHover(day)} />
              </g>
            );
          })}
        </svg>
        {hover != null && (
          <div className="chart-tip" style={{ left: Math.min(Math.max(left + (hover - 0.5) * band, 80), width - 80), top }}>
            <b>{String(hover).padStart(2, "0")}/{String(m).padStart(2, "0")}</b>
            {h ? (
              <>
                {SERIES.map((s) => <span key={s.key} style={{ display: "block" }}>{s.label}: {h[s.key]}</span>)}
                {h.justificada > 0 && <span style={{ display: "block" }}>Ausência justificada: {h.justificada}</span>}
              </>
            ) : <span>{`${data.month}-${String(hover).padStart(2, "0")}` > today ? "Ainda não chegou" : "Folga, feriado ou sem jornada"}</span>}
          </div>
        )}
      </div>
      <details className="fold">
        <summary>Ver em tabela</summary>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Dia</th>{SERIES.map((s) => <th key={s.key}>{s.label}</th>)}<th>Justificada</th></tr></thead>
            <tbody>
              {data.days.map((d) => (
                <tr key={d.date}><td>{d.date.slice(8)}/{d.date.slice(5, 7)}</td><td>{d.ok}</td><td>{d.incompleto}</td><td>{d.falta}</td><td>{d.justificada}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

const SORTS = {
  balance: { label: "Saldo", value: (p: MonthPerson) => p.balance, order: (a: MonthPerson, b: MonthPerson) => a.balance - b.balance },
  absences: { label: "Faltas", value: (p: MonthPerson) => p.absences, order: (a: MonthPerson, b: MonthPerson) => b.absences - a.absences || b.incomplete - a.incomplete },
  late: { label: "Atrasos", value: (p: MonthPerson) => p.late_days, order: (a: MonthPerson, b: MonthPerson) => b.late_days - a.late_days || b.late_minutes - a.late_minutes },
} as const;

function PeopleRank({ data, treat }: { data: MonthOverview; treat?: string }) {
  const [sort, setSort] = useState<keyof typeof SORTS>("balance");
  const S = SORTS[sort];
  const rows = [...data.people].sort((a, b) => S.order(a, b) || a.name.localeCompare(b.name));
  const scale = Math.max(1, ...rows.map((p) => Math.abs(S.value(p))));
  const link = (p: MonthPerson) => (treat ? `${treat}&user=${p.user_id}` : `/gestao/espelhos?user=${p.user_id}`);

  return (
    <section className="card" aria-labelledby="h-pessoas">
      <h3 id="h-pessoas" className="section-title" style={{ margin: 0 }}>Por pessoa</h3>
      <div className="chips-row" role="group" aria-label="Ordenar por" style={{ margin: "8px 0" }}>
        {(Object.keys(SORTS) as (keyof typeof SORTS)[]).map((k) => (
          <button key={k} className={`fchip ${sort === k ? "on" : ""}`} aria-pressed={sort === k} onClick={() => setSort(k)}>{SORTS[k].label}</button>
        ))}
      </div>
      <ul className="rank">
        {rows.map((p) => {
          const v = S.value(p);
          const share = Math.abs(v) / scale;
          const detail = sort === "balance"
            ? `${fmtMinutes(p.worked)} de ${fmtMinutes(p.expected)}`
            : sort === "absences" ? `${p.incomplete} saída(s) não registrada(s)` : `${p.late_minutes} min no total`;
          return (
            <li key={p.user_id}>
              <Link to={link(p)} aria-label={`${p.name}: ${S.label.toLowerCase()} ${sort === "balance" ? signed(v) : v}. Abrir`}>
                <span className="rank-name">{p.name}<small>{detail}</small></span>
                {sort === "balance" ? (
                  <span className="dbar" aria-hidden="true">
                    {v !== 0 && <i className={v > 0 ? "pos" : "neg"} style={{ width: `calc(${share * 50}% - 1px)` }} />}
                  </span>
                ) : (
                  <span className="dbar single" aria-hidden="true">
                    {v > 0 && <i className={sort === "late" ? "one warn-bar" : "one"} style={{ width: `${share * 100}%` }} />}
                  </span>
                )}
                <span className={`rank-val ${sort === "balance" ? (v > 0 ? "pos" : v < 0 ? "neg" : "") : ""}`}>{sort === "balance" ? signed(v) : v}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
