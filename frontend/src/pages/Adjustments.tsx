import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Adjustment, Punch } from "../types";
import { KIND_LABEL, fmtDateTimeMin, localToUtcIso, todayLocal } from "../util";

const STATUS = { pending: "Pendente", approved: "Aprovado", rejected: "Rejeitado" } as const;
const REASONS = ["Esqueci de bater o ponto", "Bati por engano", "Sem internet no momento", "Problema no aplicativo"];

function describe(a: Adjustment, tz: string, punches: Punch[]): string {
  if (a.kind === "incluir") {
    return `Incluir ${(KIND_LABEL[a.punch_kind ?? ""] ?? "marcação").toLowerCase()} em ${a.requested_at ? fmtDateTimeMin(a.requested_at, tz) : "?"}`;
  }
  const kind = a.target_kind ?? punches.find((x) => x.id === a.target_punch_id)?.kind;
  const at = a.target_at ?? punches.find((x) => x.id === a.target_punch_id)?.occurred_at;
  return kind && at ? `Desconsiderar ${KIND_LABEL[kind].toLowerCase()} de ${fmtDateTimeMin(at, tz)}` : `Desconsiderar marcação #${a.target_punch_id}`;
}

export default function Adjustments() {
  const { user, company } = useAuth();
  const tz = company!.timezone;
  const [params] = useSearchParams();
  const canApprove = user && ["manager", "hr", "admin"].includes(user.role);

  const [mine, setMine] = useState<Adjustment[]>([]);
  const [pending, setPending] = useState<Adjustment[]>([]);
  const [punches, setPunches] = useState<Punch[]>([]);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const [kind, setKind] = useState<"incluir" | "desconsiderar">("incluir");
  const [date, setDate] = useState(params.get("data") ?? todayLocal(tz));
  const [time, setTime] = useState("08:00");
  const [punchKind, setPunchKind] = useState("entrada");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, p] = await Promise.all([api<Adjustment[]>("/adjustments?mine=true"), api<Punch[]>("/punches?limit=50")]);
      setMine(m);
      setPunches(p);
      if (canApprove) {
        const pend = await api<Adjustment[]>("/adjustments?status=pending");
        setPending(pend.filter((a) => a.user_id !== user?.id));
      }
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [canApprove, user?.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const body =
        kind === "incluir"
          ? { kind, requested_at: localToUtcIso(date, time, tz), punch_kind: punchKind, reason }
          : { kind, target_punch_id: Number(target), reason };
      await api("/adjustments", { method: "POST", body });
      setReason("");
      setMsg({ type: "ok", text: "Solicitação enviada. Seu gestor vai avaliar." });
      await load();
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: number, approve: boolean) {
    try {
      await api(`/adjustments/${id}/decision`, { method: "POST", body: { approve, note: approve ? undefined : note.trim() || undefined } });
      setMsg({ type: "ok", text: approve ? "Ajuste aprovado." : "Ajuste rejeitado." });
      setRejecting(null);
      setNote("");
      await load();
    } catch (err) {
      setMsg({ type: "error", text: err instanceof Error ? err.message : "Erro" });
    }
  }

  return (
    <>
      <h1>Ajustes</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      {canApprove && pending.length > 0 && (
        <section className="card" aria-labelledby="h-aprovar">
          <h2 id="h-aprovar" className="section-title">Aguardando sua aprovação ({pending.length})</h2>
          <ul className="plain">
            {pending.map((a) => (
              <li key={a.id} className="request">
                <strong>{a.user_name ?? `#${a.user_id}`}</strong>
                <span>{describe(a, tz, [])}</span>
                <span className="muted small">“{a.reason}”</span>
                {rejecting === a.id ? (
                  <div className="request-actions">
                    <label>
                      Motivo da rejeição (opcional)
                      <input value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
                    </label>
                    <div className="row">
                      <button className="danger" onClick={() => decide(a.id, false)}>Confirmar rejeição</button>
                      <button onClick={() => { setRejecting(null); setNote(""); }}>Cancelar</button>
                    </div>
                  </div>
                ) : (
                  <div className="row request-actions">
                    <button className="primary" onClick={() => decide(a.id, true)}>Aprovar</button>
                    <button onClick={() => { setRejecting(a.id); setNote(""); }}>Rejeitar</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <form className="card" onSubmit={submit} aria-labelledby="h-nova">
        <h2 id="h-nova" className="section-title">Nova solicitação</h2>
        <div className="seg" role="group" aria-label="O que você precisa?">
          <button type="button" className={kind === "incluir" ? "on" : ""} aria-pressed={kind === "incluir"} onClick={() => setKind("incluir")}>
            Esqueci de bater
          </button>
          <button type="button" className={kind === "desconsiderar" ? "on" : ""} aria-pressed={kind === "desconsiderar"} onClick={() => setKind("desconsiderar")}>
            Bati por engano
          </button>
        </div>

        {kind === "incluir" ? (
          <>
            <div className="grid2 keep">
              <label>Data<input type="date" required value={date} max={todayLocal(tz)} onChange={(e) => setDate(e.target.value)} /></label>
              <label>Hora<input type="time" required value={time} onChange={(e) => setTime(e.target.value)} /></label>
            </div>
            <label>
              Qual marcação?
              <select value={punchKind} onChange={(e) => setPunchKind(e.target.value)}>
                {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          </>
        ) : (
          <label>
            Qual marcação foi por engano?
            <select required value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Selecione…</option>
              {punches.map((p) => (
                <option key={p.id} value={p.id}>{fmtDateTimeMin(p.occurred_at, tz)} — {KIND_LABEL[p.kind]}</option>
              ))}
            </select>
          </label>
        )}

        <label htmlFor="adj-reason">Justificativa</label>
        <div className="quick" role="group" aria-label="Justificativas comuns">
          {REASONS.map((r) => (
            <button type="button" key={r} className="fchip" onClick={() => setReason(r)}>{r}</button>
          ))}
        </div>
        <textarea id="adj-reason" required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Conte rapidamente o que aconteceu" />
        <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Enviando…" : "Enviar solicitação"}</button>
      </form>

      <section className="card" aria-labelledby="h-minhas">
        <h2 id="h-minhas" className="section-title">Minhas solicitações</h2>
        {mine.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>Você ainda não fez solicitações.</p>
        ) : (
          <ul className="plain">
            {mine.map((a) => (
              <li key={a.id} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span>{describe(a, tz, punches)}</span>
                  <span className={`tag ${a.status}`} style={{ flex: "none" }}>{STATUS[a.status]}</span>
                </div>
                <span className="muted small">{a.reason}{a.decision_note ? ` — Resposta: ${a.decision_note}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
