import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Absence, User } from "../types";
import { fmtMinutes } from "../util";

/** Peças de "ausência": o formulário (pedido pessoal ou registro pelo RH), o período e os rótulos. */

export const EMPLOYEE_KINDS: [string, string][] = [["atestado_medico", "Atestado médico"], ["abono", "Abono de falta"]];
export const HR_KINDS: [string, string][] = [
  ...EMPLOYEE_KINDS, ["ferias", "Férias"], ["licenca", "Licença"], ["afastamento_inss", "Afastamento INSS"],
];
export const ABS_STATUS: Record<string, string> = { pending: "Pendente", approved: "Aprovada", rejected: "Rejeitada", cancelled: "Cancelada" };
const br = (iso: string) => iso.split("-").reverse().join("/");

export function absencePeriod(a: Absence): string {
  const p = a.start_date === a.end_date ? br(a.start_date) : `${br(a.start_date)} a ${br(a.end_date)}`;
  return a.minutes ? `${p} (${fmtMinutes(a.minutes)})` : p;
}

export function AbsenceForm(props: {
  kinds: [string, string][]; today: string; people?: User[]; note: string; submitLabel?: string;
  onDone: () => void; onFail: (t: string) => void;
}) {
  const [kind, setKind] = useState(props.kinds[0][0]);
  const [who, setWho] = useState("");
  const [start, setStart] = useState(props.today);
  const [end, setEnd] = useState(props.today);
  const [endTouched, setEndTouched] = useState(false); // enquanto não mexer no "Até", ele acompanha o "De"
  const [partial, setPartial] = useState(false);
  const [hours, setHours] = useState("2");
  const [mins, setMins] = useState("0");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const canPartial = ["atestado_medico", "abono"].includes(kind) && start === end;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/absences", {
        method: "POST",
        body: {
          kind, start_date: start, end_date: end, reason,
          minutes: partial && canPartial ? Number(hours) * 60 + Number(mins) : null,
          user_id: props.people && who ? Number(who) : null,
        },
      });
      setReason("");
      setEndTouched(false);
      props.onDone();
    } catch (err) {
      props.onFail(err instanceof Error ? err.message : "Erro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {props.people && (
        <label>Colaborador
          <select required value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">Selecione…</option>
            {props.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      )}
      {props.kinds.length <= 2 ? (
        <div className="seg" role="group" aria-label="Tipo de ausência">
          {props.kinds.map(([v, l]) => (
            <button type="button" key={v} className={kind === v ? "on" : ""} aria-pressed={kind === v} onClick={() => setKind(v)}>{l}</button>
          ))}
        </div>
      ) : (
        <label>Tipo
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {props.kinds.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      )}
      <div className="grid2 keep">
        <label>De<input type="date" required value={start} onChange={(e) => { setStart(e.target.value); if (!endTouched || e.target.value > end) setEnd(e.target.value); }} /></label>
        <label>Até<input type="date" required value={end} min={start} onChange={(e) => { setEnd(e.target.value); setEndTouched(true); }} /></label>
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
      <label>Motivo<textarea required minLength={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <p className="muted small">{props.note}</p>
      <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Enviando…" : props.submitLabel ?? "Enviar pedido"}</button>
    </form>
  );
}
