import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { User } from "../types";
import { fmtDateTimeMin, fmtMinutes, todayLocal } from "../util";

/** Gestão > Ausências > lançamento em lote (RH e Administração): o mesmo abono ou férias coletivas para várias pessoas.
 * Primeiro confere (quem entra e quem é pulado, sem gravar); depois lança. O lote inteiro pode ser cancelado depois. */

interface Preview { batch_id: string | null; dry_run: boolean; created: { user_id: number; name: string }[];
  skipped: { user_id: number; name: string | null; reason: string }[] }
interface Batch {
  batch_id: string; kind: string; kind_label: string; start_date: string; end_date: string; minutes: number | null; reason: string;
  created_by: string | null; created_at: string; active: { absence_id: number; user_id: number; name: string }[]; cancelled: number;
}

const KINDS: [string, string][] = [["abono", "Abono"], ["ferias", "Férias coletivas"]];
const REASONS = ["Ponte de feriado", "Recesso de fim de ano", "Queda de energia", "Falta de internet no escritório", "Dispensa da empresa"];
const br = (iso: string) => iso.split("-").reverse().join("/");
const period = (b: { start_date: string; end_date: string; minutes: number | null }) =>
  (b.start_date === b.end_date ? br(b.start_date) : `${br(b.start_date)} a ${br(b.end_date)}`) + (b.minutes ? ` (${fmtMinutes(b.minutes)})` : "");

export default function AbsenceBatch({ people, onChanged, onMsg }: {
  people: User[]; onChanged: () => void; onMsg: (m: { type: "ok" | "error"; text: string }) => void;
}) {
  const { company } = useAuth();
  const tz = company!.timezone;
  const today = todayLocal(tz);
  const [kind, setKind] = useState("abono");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [partial, setPartial] = useState(false);
  const [hours, setHours] = useState("2");
  const [mins, setMins] = useState("0");
  const [reason, setReason] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [cancelling, setCancelling] = useState<string | null>(null);

  const loadBatches = useCallback(async () => {
    try { setBatches(await api<Batch[]>("/absences/batches")); } catch { /* a lista é complementar */ }
  }, []);
  useEffect(() => { void loadBatches(); }, [loadBatches]);

  const canPartial = kind === "abono" && start === end;
  const titles = useMemo(() => [...new Set(people.map((p) => p.job_title).filter(Boolean) as string[])].sort(), [people]);
  const shown = people.filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase()));
  const body = () => ({
    kind, start_date: start, end_date: end, reason: reason.trim(), user_ids: [...picked],
    minutes: partial && canPartial ? Number(hours) * 60 + Number(mins) : null,
  });

  // Qualquer mudança no formulário invalida a conferência feita antes.
  useEffect(() => { setPreview(null); }, [kind, start, end, partial, hours, mins, reason, picked]);

  function toggle(ids: number[], on: boolean) {
    setPicked((cur) => {
      const next = new Set(cur);
      for (const id of ids) if (on) next.add(id); else next.delete(id);
      return next;
    });
  }

  async function check(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setPreview(await api<Preview>("/absences/batch", { method: "POST", body: { ...body(), dry_run: true } }));
    } catch (err) {
      onMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    } finally {
      setBusy(false);
    }
  }

  async function launch() {
    setBusy(true);
    try {
      const r = await api<Preview>("/absences/batch", { method: "POST", body: body() });
      onMsg({ type: "ok", text: `Lançado para ${r.created.length} pessoa(s), já aprovado.${r.skipped.length ? ` ${r.skipped.length} pulada(s).` : ""}` });
      setPicked(new Set());
      setReason("");
      setPreview(null);
      await loadBatches();
      onChanged();
    } catch (err) {
      onMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    } finally {
      setBusy(false);
    }
  }

  async function cancelBatch(b: Batch) {
    try {
      const r = await api<{ cancelled: number }>(`/absences/batch/${b.batch_id}/cancel`, { method: "POST" });
      onMsg({ type: "ok", text: `Lote cancelado: ${r.cancelled} ausência(s). Os dias voltam a ser contados normalmente.` });
      setCancelling(null);
      await loadBatches();
      onChanged();
    } catch (err) {
      onMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    }
  }

  return (
    <>
      <details className="fold">
        <summary>Lançar para várias pessoas (em lote)</summary>
        <form onSubmit={check}>
          <p className="muted small" style={{ marginTop: 0 }}>
            Ponte de feriado, recesso, queda de energia ou férias coletivas: a mesma ausência, já aprovada, para todos os escolhidos.
          </p>
          <div className="seg" role="group" aria-label="Tipo">
            {KINDS.map(([v, l]) => (
              <button type="button" key={v} className={kind === v ? "on" : ""} aria-pressed={kind === v} onClick={() => setKind(v)}>{l}</button>
            ))}
          </div>
          <div className="grid2 keep">
            <label>De<input type="date" required value={start} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} /></label>
            <label>Até<input type="date" required value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></label>
          </div>
          {canPartial && (
            <div className="seg" role="group" aria-label="Duração">
              <button type="button" className={!partial ? "on" : ""} aria-pressed={!partial} onClick={() => setPartial(false)}>Dia inteiro</button>
              <button type="button" className={partial ? "on" : ""} aria-pressed={partial} onClick={() => setPartial(true)}>Parte do dia</button>
            </div>
          )}
          {partial && canPartial && (
            <div className="grid2 keep">
              <label>Horas<input type="number" min="0" max="12" value={hours} onChange={(e) => setHours(e.target.value)} /></label>
              <label>Minutos<input type="number" min="0" max="59" value={mins} onChange={(e) => setMins(e.target.value)} /></label>
            </div>
          )}
          <div className="quick" role="group" aria-label="Motivos comuns">
            {REASONS.map((r) => <button type="button" key={r} className="fchip" onClick={() => setReason(r)}>{r}</button>)}
          </div>
          <label>Motivo<input required minLength={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>

          <fieldset style={{ border: 0, padding: 0, margin: "0 0 12px" }}>
            <legend className="section-title">Pessoas ({picked.size} de {people.length})</legend>
            <div className="quick" role="group" aria-label="Selecionar várias">
              <button type="button" className="fchip" onClick={() => toggle(people.map((p) => p.id), true)}>Todas</button>
              <button type="button" className="fchip" onClick={() => setPicked(new Set())}>Nenhuma</button>
              {titles.map((t) => (
                <button type="button" key={t} className="fchip" onClick={() => toggle(people.filter((p) => p.job_title === t).map((p) => p.id), true)}>+ {t}</button>
              ))}
            </div>
            {people.length > 8 && (
              <div className="search"><input type="search" placeholder="Buscar pelo nome" aria-label="Buscar pelo nome" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
            )}
            <div style={{ maxHeight: 280, overflowY: "auto" }}>
              {shown.map((p) => (
                <label key={p.id} className="check" style={{ margin: "0 0 8px" }}>
                  <input type="checkbox" checked={picked.has(p.id)} onChange={(e) => toggle([p.id], e.target.checked)} />
                  <span>{p.name}{p.job_title && <span className="muted small"> · {p.job_title}</span>}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {!preview && (
            <button className="primary" style={{ width: "100%" }} disabled={busy || picked.size === 0 || reason.trim().length < 3}>
              {busy ? "Conferindo…" : picked.size ? `Conferir ${picked.size} pessoa(s)` : "Escolha as pessoas"}
            </button>
          )}
        </form>

        {preview && (
          <div className="card" role="status" style={{ marginTop: 8 }}>
            <p style={{ marginTop: 0 }}>
              <b>{preview.created.length}</b> pessoa(s) recebem {KINDS.find(([v]) => v === kind)?.[1].toLowerCase()} em{" "}
              {period({ start_date: start, end_date: end, minutes: partial && canPartial ? Number(hours) * 60 + Number(mins) : null })}.
            </p>
            {preview.skipped.length > 0 && (
              <>
                <p className="section-title">Ficam de fora ({preview.skipped.length})</p>
                <ul className="plain small">
                  {preview.skipped.map((s) => <li key={s.user_id}><b>{s.name ?? `#${s.user_id}`}</b>: {s.reason}</li>)}
                </ul>
              </>
            )}
            <div className="row">
              <button className="primary" disabled={busy || preview.created.length === 0} onClick={launch}>
                {busy ? "Lançando…" : `Lançar para ${preview.created.length} pessoa(s)`}
              </button>
              <button onClick={() => setPreview(null)}>Voltar</button>
            </div>
          </div>
        )}
      </details>

      {batches.length > 0 && (
        <details className="fold">
          <summary>Lotes lançados ({batches.length})</summary>
          <ul className="plain">
            {batches.map((b) => (
              <li key={b.batch_id} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span><strong>{b.kind_label}</strong> · {period(b)} · {b.reason}</span>
                  <span className={`tag ${b.active.length ? "approved" : "cancelled"}`} style={{ flex: "none" }}>
                    {b.active.length ? `${b.active.length} pessoa(s)` : "Cancelado"}
                  </span>
                </div>
                <span className="muted small">
                  {b.created_by ?? "—"} em {fmtDateTimeMin(b.created_at, tz)}
                  {b.cancelled > 0 && b.active.length > 0 ? ` · ${b.cancelled} cancelada(s)` : ""}
                  {b.active.length > 0 && `: ${b.active.map((a) => a.name).join(", ")}`}
                </span>
                {b.active.length > 0 && (cancelling === b.batch_id ? (
                  <div className="row request-actions">
                    <button className="danger" onClick={() => cancelBatch(b)}>Cancelar o lote inteiro</button>
                    <button onClick={() => setCancelling(null)}>Voltar</button>
                  </div>
                ) : (
                  <button className="link" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setCancelling(b.batch_id)}>Cancelar lote</button>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
