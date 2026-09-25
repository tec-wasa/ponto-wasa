import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Dashboard, DashboardPerson, Mirror } from "../types";
import { fmtMinutes, parseUtc, todayLocal } from "../util";

const WEEK = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const DOT: Record<string, string> = { presente: "working", em_intervalo: "break", sem_marcacao: "danger", incompleto: "danger", justificada: "working" };

/** As 7 datas (AAAA-MM-DD) da semana de hoje, de segunda a domingo. */
export function weekDates(today: string): string[] {
  const base = new Date(`${today}T12:00:00Z`);
  const monday = new Date(base.getTime() - ((base.getUTCDay() + 6) % 7) * 86_400_000);
  return Array.from({ length: 7 }, (_, i) => new Date(monday.getTime() + i * 86_400_000).toISOString().slice(0, 10));
}

export interface Bar { date: string; label: string; worked: number; expected: number; partial: boolean; today: boolean }

/** Soma o turno em andamento à barra do dia em que ele começou (o cálculo do Espelho conta o tempo no dia da entrada).
 * O servidor só conta jornadas encerradas: sem isto, o dia de hoje pareceria vazio até a saída. */
export function withOpenTime(bars: Bar[], open: { since: string; minutes: number } | undefined, tz: string): Bar[] {
  if (!open || open.minutes <= 0) return bars;
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(parseUtc(open.since));
  return bars.map((b) => (b.date === day ? { ...b, worked: b.worked + open.minutes, partial: true } : b));
}

/** Coluna lateral do desktop (design.md): resumo semanal e equipe. No celular vira a faixa de chips da equipe. */
/** `open`: turno em andamento (desde quando e quantos minutos), para o gráfico contar o tempo corrente. */
export default function PunchSide({ refreshKey, open }: { refreshKey: number; open?: { since: string; minutes: number } }) {
  const { user, company } = useAuth();
  const tz = company!.timezone;
  const isApprover = !!user && ["manager", "hr", "admin"].includes(user.role);
  const [bars, setBars] = useState<Bar[] | null>(null);
  const [people, setPeople] = useState<DashboardPerson[]>([]);

  useEffect(() => {
    let alive = true;
    const today = todayLocal(tz);
    const dates = weekDates(today);
    const months = [...new Set(dates.map((d) => d.slice(0, 7)))];
    Promise.all(months.map((m) => api<Mirror>(`/mirror?month=${m}`)))
      .then((res) => {
        if (!alive) return;
        const byDate = new Map(res.flatMap((r) => r.days).map((d) => [d.date, d]));
        setBars(dates.map((date, i) => {
          const d = byDate.get(date);
          return {
            date, label: WEEK[i], worked: d?.worked ?? 0, expected: d?.expected ?? 0, today: date === today,
            partial: date === today || d?.status === "incompleto" || d?.status === "hoje", // dia em andamento ou sem saída
          };
        }));
      })
      .catch(() => alive && setBars(null));
    return () => {
      alive = false;
    };
  }, [tz, refreshKey]);

  useEffect(() => {
    if (!isApprover) return;
    let alive = true;
    const load = () => api<Dashboard>("/dashboard").then((d) => alive && setPeople(d.people)).catch(() => undefined);
    load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [isApprover, refreshKey]);

  const shown = bars ? withOpenTime(bars, open, tz) : null;
  const max = Math.max(60, ...(shown ?? []).map((b) => Math.max(b.worked, b.expected)));
  const total = (shown ?? []).reduce((s, b) => s + b.worked, 0);
  const expected = (shown ?? []).reduce((s, b) => s + b.expected, 0);
  const firstName = (n: string) => n.trim().split(/\s+/)[0];

  return (
    <aside className="punch-side" aria-label="Resumo">
      {isApprover && people.length > 0 && (
        <div className="team-chips" role="list" aria-label="Equipe agora">
          {people.map((p) => (
            <Link key={p.user_id} to={`/espelho?user=${p.user_id}`} className="chip-person" role="listitem" aria-label={`${p.name}: ${p.state_label}`}>
              <span className={`dot ${DOT[p.state] ?? ""}`} aria-hidden="true" />{firstName(p.name)}
            </Link>
          ))}
        </div>
      )}

      {shown && (
        <section className="card side-week" aria-labelledby="h-semana">
          <h2 id="h-semana" className="section-title">Esta semana</h2>
          <p className="week-total"><b>{fmtMinutes(total)}</b><span className="muted small"> de {fmtMinutes(expected)} previstas</span></p>
          <div className="week-chart" role="list">
            {shown.map((b) => (
              <div key={b.date} role="listitem" className={`week-bar ${b.partial ? "partial" : ""} ${b.today ? "today" : ""}`}
                aria-label={`${b.label}: ${fmtMinutes(b.worked)} trabalhadas`}>
                <i style={{ height: `${Math.max(3, (b.worked / max) * 100)}%` }} />
                <span>{b.label}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {isApprover && people.length > 0 && (
        <section className="card side-team" aria-labelledby="h-equipe-side">
          <h2 id="h-equipe-side" className="section-title">Equipe</h2>
          <ul className="plain">
            {people.slice(0, 8).map((p) => (
              <li key={p.user_id}>
                <Link to={`/espelho?user=${p.user_id}`} className="side-person">
                  <span className={`dot ${DOT[p.state] ?? ""}`} aria-hidden="true" />
                  <span className="side-name">{p.name}</span>
                  <span className="muted small">{p.state_label}</span>
                </Link>
              </li>
            ))}
          </ul>
          {people.length > 8 && <Link to="/equipe" className="small">Ver toda a equipe ({people.length})</Link>}
        </section>
      )}
    </aside>
  );
}
