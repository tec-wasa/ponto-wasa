import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, blobUrl, download } from "../api";
import { useAuth } from "../auth";
import type { Mirror as MirrorT, MirrorDay, Punch, User } from "../types";
import { KIND_LABEL, currentMonth, fmtDateTimeMin, fmtMinutes, fmtMonth, shiftMonth } from "../util";

const STATUS: Record<string, string> = {
  ok: "Regular", folga: "Folga", falta: "Falta", incompleto: "Incompleto", hoje: "Hoje", futuro: "—",
  anterior: "Antes da admissão", justificada: "Justificada", feriado: "Feriado",
};

type View = "uteis" | "atencao" | "todos";

const NEEDS_ATTENTION = (d: MirrorDay) => d.status === "falta" || d.status === "incompleto" || d.warnings.length > 0;
const QUIET = ["folga", "feriado", "futuro", "anterior"];

/** "08:00 entrada" -> ["08:00", "Entrada"] (o servidor manda o tipo cru). */
function splitPunch(p: string): [string, string] {
  const m = /^(\d\d:\d\d) (\w+)(.*)$/.exec(p);
  return m ? [m[1], (KIND_LABEL[m[2]] ?? m[2]) + m[3]] : [p, ""];
}

function dayParts(date: string): { num: string; week: string } {
  const d = new Date(`${date}T12:00:00Z`);
  return {
    num: String(d.getUTCDate()).padStart(2, "0"),
    week: d.toLocaleDateString("pt-BR", { weekday: "short", timeZone: "UTC" }).replace(".", ""),
  };
}

/** `self`: Meu ponto > Registros (o meu espelho e os comprovantes). `team`: Gestão > Espelhos (escolher a pessoa). */
export default function Mirror({ mode = "self" }: { mode?: "self" | "team" }) {
  const { user, company, can } = useAuth();
  const team = mode === "team";
  const tz = company!.timezone;
  const [month, setMonth] = useState(() => currentMonth(tz));
  const [people, setPeople] = useState<User[]>([]);
  const [params] = useSearchParams();
  const [target, setTarget] = useState<number | "">(Number(params.get("user")) || "");
  const [data, setData] = useState<MirrorT | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [view, setView] = useState<View>("uteis");
  const [recent, setRecent] = useState<Punch[]>([]);
  const [photos, setPhotos] = useState<{ punch_id: number; kind: string; occurred_at: string; nsr: number }[]>([]);
  const [photoShown, setPhotoShown] = useState<{ id: number; url: string } | null>(null);
  const canSeePhotos = team && can("photos.view") && !!company?.photo_enabled;

  useEffect(() => {
    if (!team) return;
    api<User[]>("/users").then((u) => setPeople(u.filter((p) => p.id !== user?.id && p.tracks_time !== false))).catch(() => undefined);
  }, [team, user?.id]);

  useEffect(() => {
    if (team && !target) { setData(null); return; }  // gestão: primeiro escolher a pessoa
    let cancelled = false;
    setLoading(true);
    setError("");
    api<MirrorT>(`/mirror?month=${month}${target ? `&user_id=${target}` : ""}`)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && (setData(null), setError(e instanceof Error ? e.message : "Erro")))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [month, target, team]);

  const own = !team;

  useEffect(() => {
    if (own) api<Punch[]>("/punches?limit=20").then(setRecent).catch(() => undefined);
  }, [own, month]);

  useEffect(() => {
    setPhotos([]);
    if (canSeePhotos && target) api<typeof photos>(`/photos?user_id=${target}&month=${month}`).then(setPhotos).catch(() => undefined);
  }, [canSeePhotos, target, month]);

  useEffect(() => () => { if (photoShown) URL.revokeObjectURL(photoShown.url); }, [photoShown]);

  async function showPhoto(id: number) {
    setError("");
    try {
      setPhotoShown({ id, url: await blobUrl(`/punches/${id}/photo`) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Foto indisponível");
    }
  }

  async function receiptPdf(p: Punch) {
    setError("");
    try {
      await download(`/punches/${p.id}/receipt.pdf`, `comprovante-NSR${p.nsr}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao baixar o comprovante");
    }
  }

  async function officialPdf(modelo: "folha" | "detalhado") {
    setPdfBusy(true);
    setError("");
    try {
      await download(`/mirror/official.pdf?month=${month}&modelo=${modelo}${target ? `&user_id=${target}` : ""}`,
        `${modelo === "folha" ? "folha-de-ponto" : "espelho"}-${month}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar o PDF");
    } finally {
      setPdfBusy(false);
    }
  }

  async function allFolhas() {
    setPdfBusy(true);
    setError("");
    try {
      await download(`/mirror/folhas.pdf?month=${month}`, `folhas-de-ponto-${month}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar as folhas");
    } finally {
      setPdfBusy(false);
    }
  }

  const t = data?.totals;
  const attention = useMemo(() => (data?.days ?? []).filter(NEEDS_ATTENTION), [data]);
  const shown = useMemo(() => {
    const days = data?.days ?? [];
    if (view === "atencao") return attention;
    if (view === "uteis") return days.filter((d) => !QUIET.includes(d.status) || d.punches.length > 0);
    return days;
  }, [data, view, attention]);

  return (
    <>
      <h1>{team ? "Espelhos" : "Meus registros"}</h1>

      <div className="month-nav">
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Mês anterior">‹</button>
        <strong className="month-title" aria-live="polite">{fmtMonth(month)}</strong>
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Próximo mês" disabled={month >= currentMonth(tz)}>›</button>
      </div>

      {team && (
        <label>
          Colaborador
          <select value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Escolha…</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      )}
      {team && !target && people.length === 0 && <p className="card muted">Ninguém para acompanhar ainda.</p>}
      {team && (
        <p className="small" style={{ margin: "0 0 12px" }}>
          <button className="link" style={{ padding: 0 }} disabled={pdfBusy} onClick={allFolhas}>Folhas de ponto de todos de {fmtMonth(month)} (um PDF, uma página por pessoa)</button>
        </p>
      )}
      {team && target && can("approvals") && (
        <p className="small" style={{ margin: "0 0 12px" }}><Link to={`/gestao/tratamento?user=${target}&mes=${month}`}>Corrigir este mês em Tratamento →</Link></p>
      )}

      {error && <p className="alert error" role="alert">{error}</p>}
      {loading && !data && <p className="muted" role="status">Carregando…</p>}

      {t && (
        <section className="card summary" aria-label="Resumo do mês">
          <div className="summary-main">
            <div><span className="section-title">Trabalhadas</span><b>{fmtMinutes(t.worked_minutes)}</b></div>
            <div><span className="section-title">Previstas</span><b>{fmtMinutes(t.expected_minutes)}</b></div>
            <div>
              <span className="section-title">Saldo</span>
              <b className={t.balance_minutes >= 0 ? "pos" : "neg"}>{t.balance_minutes > 0 ? "+" : ""}{fmtMinutes(t.balance_minutes)}</b>
            </div>
          </div>
          <p className="summary-line muted small">
            Faltas <b>{t.absences}</b> · Justificados <b>{t.justified_days}</b> · Incompletos <b>{t.incomplete_days}</b>
          </p>
          {data?.overtime && data.overtime.total > 0 && (
            <p className="summary-line muted small" style={{ marginTop: -4 }}>
              Horas extras <b>{fmtMinutes(data.overtime.total)}</b>
              {data.overtime.by_percent.map((p) => <span key={p.percent}> · a {p.percent}% <b>{fmtMinutes(p.minutes)}</b></span>)}
            </p>
          )}
          <div className="row">
            <button onClick={() => officialPdf("folha")} disabled={pdfBusy}>{pdfBusy ? "Gerando…" : "Folha de ponto (PDF)"}</button>
            <button className="link" onClick={() => officialPdf("detalhado")} disabled={pdfBusy}>Espelho detalhado (com NSR)</button>
          </div>
        </section>
      )}

      {data && (
        <>
          <div className="seg" role="group" aria-label="Quais dias mostrar">
            <button className={view === "uteis" ? "on" : ""} aria-pressed={view === "uteis"} onClick={() => setView("uteis")}>Dias úteis</button>
            <button className={view === "atencao" ? "on" : ""} aria-pressed={view === "atencao"} onClick={() => setView("atencao")}>
              Pendências{attention.length > 0 && <span className="count">{attention.length}</span>}
            </button>
            <button className={view === "todos" ? "on" : ""} aria-pressed={view === "todos"} onClick={() => setView("todos")}>Todos</button>
          </div>

          <section className="card" style={{ padding: "4px 16px" }}>
            {shown.length === 0 && (
              <p className="muted">{view === "atencao" ? "Nenhuma pendência neste mês." : "Nenhum dia para mostrar."}</p>
            )}
            {shown.map((d) => {
              const { num, week } = dayParts(d.date);
              const times = d.punches.map((p) => splitPunch(p)[0]);
              const flag = NEEDS_ATTENTION(d);
              return (
                <details className="day-row" key={d.date}>
                  <summary>
                    <span className="day-date"><b>{num}</b><small>{week}</small></span>
                    <span className="day-main">
                      <span>
                        <span className={`tag ${d.status}`}>{STATUS[d.status]}</span>
                        {d.justification && <span className="muted small"> {d.justification}</span>}
                        {d.holiday && <span className="muted small"> {d.holiday}</span>}
                        {flag && d.status !== "falta" && d.status !== "incompleto" && <span className="tag falta" style={{ marginLeft: 4 }}>Alerta</span>}
                      </span>
                      <span className="muted small day-times">{times.length ? times.join(" · ") : "Sem marcações"}</span>
                    </span>
                    <span className="day-num">
                      {d.worked ? fmtMinutes(d.worked) : ""}
                      {d.balance ? <small className={d.balance > 0 ? "pos" : "neg"}>{d.balance > 0 ? "+" : ""}{fmtMinutes(d.balance)}</small> : null}
                    </span>
                  </summary>
                  <div className="day-body">
                    {d.punches.length > 0 && (
                      <ul className="plain">
                        {d.punches.map((p) => {
                          const [time, label] = splitPunch(p);
                          return <li key={p}><span>{label}</span><b className="when">{time}</b></li>;
                        })}
                      </ul>
                    )}
                    {d.warnings.map((w) => <p className="warn small" key={w}>⚠ {w}</p>)}
                    {own && d.status !== "futuro" && (
                      <Link className="day-action" to={`/solicitacoes?data=${d.date}`}>Pedir correção deste dia</Link>
                    )}
                  </div>
                </details>
              );
            })}
          </section>
        </>
      )}

      {canSeePhotos && target && photos.length > 0 && (
        <section className="card" aria-labelledby="h-fotos">
          <h2 id="h-fotos" className="section-title">Fotos das batidas</h2>
          <p className="muted small">Só o RH e a Administração veem. Cada consulta fica na auditoria e as fotos somem quando o mês é fechado.</p>
          <ul className="plain">
            {photos.map((p) => (
              <li key={p.punch_id}>
                <span>{KIND_LABEL[p.kind] ?? p.kind}<span className="muted small"> · {fmtDateTimeMin(p.occurred_at, tz)} · NSR {p.nsr}</span></span>
                <button className="link" style={{ minHeight: 36 }} onClick={() => showPhoto(p.punch_id)}>Ver foto</button>
              </li>
            ))}
          </ul>
          {photoShown && (
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <img src={photoShown.url} alt="Foto da batida" style={{ maxWidth: "100%", borderRadius: 14 }} />
              <div><button className="link" onClick={() => setPhotoShown(null)}>Fechar foto</button></div>
            </div>
          )}
        </section>
      )}

      {own && recent.length > 0 && (
        <section className="card" aria-labelledby="h-comp">
          <h2 id="h-comp" className="section-title">Comprovantes das últimas batidas</h2>
          <ul className="plain">
            {recent.map((p) => (
              <li key={p.id}>
                <span>
                  {KIND_LABEL[p.kind] ?? p.kind}
                  <span className="muted small"> · {fmtDateTimeMin(p.occurred_at, tz)} · NSR {p.nsr} · {p.origin}{p.offline ? " · sem internet" : ""}</span>
                </span>
                <button className="link" style={{ minHeight: 36 }} onClick={() => receiptPdf(p)} aria-label={`Baixar comprovante de ${KIND_LABEL[p.kind]} do NSR ${p.nsr}`}>PDF</button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
