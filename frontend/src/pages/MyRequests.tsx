import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Absence, Adjustment, Punch } from "../types";
import { todayLocal } from "../util";
import { ABS_STATUS, AbsenceForm, EMPLOYEE_KINDS, absencePeriod } from "./Absences";
import { ADJ_STATUS, AdjustmentForm, describeAdjustment } from "./Adjustments";

type Row = { key: string; when: number; title: string; detail: string; status: string; statusLabel: string; absence?: Absence };

/** Meu ponto > Solicitações: pedir correção de marcação ou justificar ausência, e acompanhar os pedidos. */
export default function MyRequests() {
  const { company } = useAuth();
  const tz = company!.timezone;
  const [params] = useSearchParams();
  const [what, setWhat] = useState<"ajuste" | "ausencia">(params.get("tipo") === "ausencia" ? "ausencia" : "ajuste");
  const [adjs, setAdjs] = useState<Adjustment[]>([]);
  const [abs, setAbs] = useState<Absence[]>([]);
  const [punches, setPunches] = useState<Punch[]>([]);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b, p] = await Promise.all([
        api<Adjustment[]>("/adjustments?mine=true"), api<Absence[]>("/absences?mine=true"), api<Punch[]>("/punches?limit=50"),
      ]);
      setAdjs(a); setAbs(b); setPunches(p);
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const sent = () => { setMsg({ type: "ok", text: "Pedido enviado. Acompanhe a situação logo abaixo." }); void load(); };
  const fail = (t: string) => setMsg({ type: "error", text: t });

  async function cancel(a: Absence) {
    try {
      await api(`/absences/${a.id}/cancel`, { method: "POST" });
      setMsg({ type: "ok", text: "Pedido cancelado." });
      setCancelling(null);
      await load();
    } catch (e) {
      fail(e instanceof Error ? e.message : "Erro");
    }
  }

  const rows: Row[] = [
    ...adjs.map((a) => ({
      key: `j${a.id}`, when: a.id, title: describeAdjustment(a, tz, punches),
      detail: a.reason + (a.decision_note ? ` — Resposta: ${a.decision_note}` : ""), status: a.status, statusLabel: ADJ_STATUS[a.status],
    })),
    ...abs.map((a) => ({
      key: `b${a.id}`, when: a.id, title: `${a.kind_label} · ${absencePeriod(a)}`,
      detail: (a.reason ?? "") + (a.decision_note ? ` — Resposta: ${a.decision_note}` : ""), status: a.status, statusLabel: ABS_STATUS[a.status], absence: a,
    })),
  ].sort((x, y) => (x.status === "pending" ? 0 : 1) - (y.status === "pending" ? 0 : 1) || y.when - x.when);

  return (
    <>
      <h1>Solicitações</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      <section className="card" aria-labelledby="h-novo">
        <h2 id="h-novo" className="section-title">Novo pedido</h2>
        <div className="seg" role="group" aria-label="Tipo de pedido">
          <button type="button" className={what === "ajuste" ? "on" : ""} aria-pressed={what === "ajuste"} onClick={() => setWhat("ajuste")}>Corrigir marcação</button>
          <button type="button" className={what === "ausencia" ? "on" : ""} aria-pressed={what === "ausencia"} onClick={() => setWhat("ausencia")}>Atestado ou abono</button>
        </div>
        {what === "ajuste" ? (
          <AdjustmentForm tz={tz} punches={punches} initialDate={params.get("data") ?? undefined} onDone={sent} onFail={fail} />
        ) : (
          <AbsenceForm kinds={EMPLOYEE_KINDS} today={todayLocal(tz)} onDone={sent} onFail={fail}
            note="Não informe diagnóstico nem CID. Entregue o comprovante original a quem cuida do pessoal na empresa." />
        )}
      </section>

      <section className="card" aria-labelledby="h-meus">
        <h2 id="h-meus" className="section-title">Meus pedidos</h2>
        {rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nenhum pedido ainda.</p> : (
          <ul className="plain">
            {rows.map((r) => (
              <li key={r.key} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span>{r.title}</span>
                  <span className={`tag ${r.status}`} style={{ flex: "none" }}>{r.statusLabel}</span>
                </div>
                <span className="muted small">{r.detail}</span>
                {r.absence && r.status === "pending" && (cancelling === r.absence.id ? (
                  <div className="row request-actions">
                    <button className="danger" onClick={() => cancel(r.absence!)}>Confirmar cancelamento</button>
                    <button onClick={() => setCancelling(null)}>Voltar</button>
                  </div>
                ) : (
                  <button className="link" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setCancelling(r.absence!.id)}>Cancelar pedido</button>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
