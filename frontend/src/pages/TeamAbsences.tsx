import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Absence, User } from "../types";
import { todayLocal } from "../util";
import AbsenceBatch from "./AbsenceBatch";
import { ABS_STATUS, AbsenceForm, HR_KINDS, absencePeriod } from "./Absences";

/** Gestão > Ausências: as ausências da equipe/empresa e, para o RH, o registro direto (já aprovado) e o cancelamento. */
export default function TeamAbsences() {
  const { user, company, can } = useAuth();
  const tz = company!.timezone;
  const register = can("absences.register");
  const [list, setList] = useState<Absence[]>([]);
  const [people, setPeople] = useState<User[]>([]);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setList((await api<Absence[]>("/absences")).filter((a) => a.user_id !== user?.id));
      if (register) setPeople((await api<User[]>("/users")).filter((p) => p.active && p.tracks_time !== false));
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [register, user?.id]);
  useEffect(() => { void load(); }, [load]);

  async function cancel(a: Absence) {
    try {
      await api(`/absences/${a.id}/cancel`, { method: "POST" });
      setMsg({ type: "ok", text: "Ausência cancelada. Os dias voltam a ser contados normalmente." });
      setCancelling(null);
      await load();
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  const pending = list.filter((a) => a.status === "pending").length;

  return (
    <>
      <h1>Ausências</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      {pending > 0 && <p className="alert info">{pending} pedido(s) aguardando decisão. <Link to="/gestao/aprovacoes">Abrir Aprovações</Link></p>}

      {register && (
        <details className="fold">
          <summary>Registrar ausência de um colaborador</summary>
          <AbsenceForm kinds={HR_KINDS} today={todayLocal(tz)} people={people} submitLabel="Registrar"
            onDone={() => { setMsg({ type: "ok", text: "Ausência registrada e já aprovada." }); void load(); }}
            onFail={(t) => setMsg({ type: "error", text: t })}
            note="O registro feito aqui entra aprovado e fica na trilha de auditoria. Férias, licenças e afastamentos só são registrados aqui." />
        </details>
      )}

      {register && <AbsenceBatch people={people} onChanged={() => void load()} onMsg={(m) => { setMsg(m); window.scrollTo({ top: 0, behavior: "smooth" }); }} />}

      <section className="card" aria-labelledby="h-lista">
        <h2 id="h-lista" className="section-title">{user?.scope === "team" ? "Ausências da equipe" : "Ausências da empresa"}</h2>
        {list.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nenhuma ausência registrada.</p> : (
          <ul className="plain">
            {list.map((a) => (
              <li key={a.id} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span><strong>{a.user_name}</strong> · {a.kind_label} · {absencePeriod(a)}{a.batch_id && <span className="muted small"> · em lote</span>}</span>
                  <span className={`tag ${a.status}`} style={{ flex: "none" }}>{ABS_STATUS[a.status]}</span>
                </div>
                <span className="muted small">{a.restricted ? "Motivo restrito ao RH (dado de saúde)" : a.reason}</span>
                {register && ["approved", "pending"].includes(a.status) && (cancelling === a.id ? (
                  <div className="row request-actions">
                    <button className="danger" onClick={() => cancel(a)}>Confirmar cancelamento</button>
                    <button onClick={() => setCancelling(null)}>Voltar</button>
                  </div>
                ) : (
                  <button className="link" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setCancelling(a.id)}>Cancelar</button>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
