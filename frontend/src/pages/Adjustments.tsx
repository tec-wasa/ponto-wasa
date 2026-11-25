import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Adjustment, Punch } from "../types";
import { KIND_LABEL, fmtDateTimeMin, localToUtcIso, todayLocal } from "../util";

/** Peças de "ajuste de marcação": o pedido (Meu ponto > Solicitações) e a descrição usada também em Aprovações. */

export const ADJ_STATUS = { pending: "Pendente", approved: "Aprovado", rejected: "Rejeitado" } as const;
const REASONS = ["Esqueci de bater o ponto", "Bati por engano", "Sem internet no momento", "Problema no aplicativo"];

export function describeAdjustment(a: Adjustment, tz: string, punches: Punch[] = []): string {
  if (a.kind === "incluir") {
    return `Incluir ${(KIND_LABEL[a.punch_kind ?? ""] ?? "marcação").toLowerCase()} em ${a.requested_at ? fmtDateTimeMin(a.requested_at, tz) : "?"}`;
  }
  const kind = a.target_kind ?? punches.find((x) => x.id === a.target_punch_id)?.kind;
  const at = a.target_at ?? punches.find((x) => x.id === a.target_punch_id)?.occurred_at;
  return kind && at ? `Desconsiderar ${KIND_LABEL[kind].toLowerCase()} de ${fmtDateTimeMin(at, tz)}` : `Desconsiderar marcação #${a.target_punch_id}`;
}

export function AdjustmentForm({ tz, punches, initialDate, onDone, onFail }: {
  tz: string; punches: Punch[]; initialDate?: string; onDone: () => void; onFail: (t: string) => void;
}) {
  const [kind, setKind] = useState<"incluir" | "desconsiderar">("incluir");
  const [date, setDate] = useState(initialDate ?? todayLocal(tz));
  const [time, setTime] = useState("08:00");
  const [punchKind, setPunchKind] = useState("entrada");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const body = kind === "incluir"
        ? { kind, requested_at: localToUtcIso(date, time, tz), punch_kind: punchKind, reason }
        : { kind, target_punch_id: Number(target), reason };
      await api("/adjustments", { method: "POST", body });
      setReason("");
      onDone();
    } catch (err) {
      onFail(err instanceof Error ? err.message : "Erro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="seg" role="group" aria-label="O que aconteceu?">
        <button type="button" className={kind === "incluir" ? "on" : ""} aria-pressed={kind === "incluir"} onClick={() => setKind("incluir")}>Esqueci de bater</button>
        <button type="button" className={kind === "desconsiderar" ? "on" : ""} aria-pressed={kind === "desconsiderar"} onClick={() => setKind("desconsiderar")}>Bati por engano</button>
      </div>
      {kind === "incluir" ? (
        <>
          <div className="grid2 keep">
            <label>Data<input type="date" required value={date} max={todayLocal(tz)} onChange={(e) => setDate(e.target.value)} /></label>
            <label>Hora<input type="time" required value={time} onChange={(e) => setTime(e.target.value)} /></label>
          </div>
          <label>Qual marcação?
            <select value={punchKind} onChange={(e) => setPunchKind(e.target.value)}>
              {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </>
      ) : (
        <label>Qual marcação foi por engano?
          <select required value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Selecione…</option>
            {punches.map((p) => <option key={p.id} value={p.id}>{fmtDateTimeMin(p.occurred_at, tz)} — {KIND_LABEL[p.kind]}</option>)}
          </select>
        </label>
      )}
      <label htmlFor="adj-reason">Justificativa</label>
      <div className="quick" role="group" aria-label="Justificativas comuns">
        {REASONS.map((r) => <button type="button" key={r} className="fchip" onClick={() => setReason(r)}>{r}</button>)}
      </div>
      <textarea id="adj-reason" required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Conte rapidamente o que aconteceu" />
      <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Enviando…" : "Enviar pedido"}</button>
    </form>
  );
}
