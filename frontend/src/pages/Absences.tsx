import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Absence, User } from "../types";
import { fmtMinutes, todayLocal } from "../util";

const EMPLOYEE_KINDS: [string, string][] = [["atestado_medico", "Atestado médico"], ["abono", "Abono de falta"]];
const HR_KINDS: [string, string][] = [
  ...EMPLOYEE_KINDS, ["ferias", "Férias"], ["licenca", "Licença"], ["afastamento_inss", "Afastamento INSS"],
];
const STATUS: Record<string, string> = { pending: "Pendente", approved: "Aprovada", rejected: "Rejeitada", cancelled: "Cancelada" };
const br = (iso: string) => iso.split("-").reverse().join("/");

function period(a: Absence): string {
  const p = a.start_date === a.end_date ? br(a.start_date) : `${br(a.start_date)} a ${br(a.end_date)}`;
  return a.minutes ? `${p} (${fmtMinutes(a.minutes)})` : p;
}

export default function Absences() {
  const { user, company } = useAuth();
  const tz = company!.timezone;
  const today = todayLocal(tz);
  const isHr = !!user && ["hr", "admin"].includes(user.role);
  const isApprover = !!user && ["manager", "hr", "admin"].includes(user.role);

  const [list, setList] = useState<Absence[]>([]);
  const [people, setPeople] = useState<User[]>([]);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [cancelling, setCancelling] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setList(await api<Absence[]>("/absences"));
      if (isHr) setPeople((await api<User[]>("/users")).filter((p) => p.active));
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [isHr]);

  useEffect(() => {
    load();
  }, [load]);

  const notify = (type: "ok" | "error", text: string) => setMsg({ type, text });

  async function decide(a: Absence, approve: boolean) {
    try {
      await api(`/absences/${a.id}/decision`, { method: "POST", body: { approve, note: approve ? undefined : note.trim() || undefined } });
      notify("ok", approve ? "Ausência aprovada." : "Ausência rejeitada.");
      setRejecting(null);
      setNote("");
      await load();
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Erro");
    }
  }

  async function cancel(a: Absence) {
    try {
      await api(`/absences/${a.id}/cancel`, { method: "POST" });
      notify("ok", "Ausência cancelada. Os dias voltam a ser contados normalmente.");
      setCancelling(null);
      await load();
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Erro");
    }
  }

  const CancelButton = ({ a, label }: { a: Absence; label: string }) =>
    cancelling === a.id ? (
      <div className="row request-actions">
        <button className="danger" onClick={() => cancel(a)}>Confirmar cancelamento</button>
        <button onClick={() => setCancelling(null)}>Voltar</button>
      </div>
    ) : (
      <button className="link" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setCancelling(a.id)}>{label}</button>
    );

  const pendingForMe = list.filter((a) => a.status === "pending" && a.user_id !== user?.id && isApprover);
  const mine = list.filter((a) => a.user_id === user?.id);
  const others = list.filter((a) => a.user_id !== user?.id && a.status !== "pending");

  return (
    <>
      <h1>Ausências</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}

      {pendingForMe.length > 0 && (
        <section className="card" aria-labelledby="h-decidir">
          <h2 id="h-decidir" className="section-title">Aguardando sua decisão ({pendingForMe.length})</h2>
          <ul className="plain">
            {pendingForMe.map((a) => (
              <li key={a.id} className="request">
                <strong>{a.user_name}</strong>
                <span>{a.kind_label} · {period(a)}</span>
                <span className="muted small">{a.restricted ? "Motivo e anexo restritos ao RH (dado de saúde)." : `“${a.reason}”`}</span>
                {rejecting === a.id ? (
                  <div className="request-actions">
                    <label>Motivo da rejeição (opcional)<input value={note} onChange={(e) => setNote(e.target.value)} autoFocus /></label>
                    <div className="row">
                      <button className="danger" onClick={() => decide(a, false)}>Confirmar rejeição</button>
                      <button onClick={() => { setRejecting(null); setNote(""); }}>Cancelar</button>
                    </div>
                  </div>
                ) : (
                  <div className="row request-actions">
                    <button className="primary" onClick={() => decide(a, true)}>Aprovar</button>
                    <button onClick={() => { setRejecting(a.id); setNote(""); }}>Rejeitar</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <RequestForm
        title="Pedir atestado ou abono" kinds={EMPLOYEE_KINDS} today={today}
        onDone={() => { notify("ok", "Pedido enviado. Você será avisado quando for decidido."); load(); }} onFail={(t) => notify("error", t)}
        note="Não informe diagnóstico nem CID: o motivo é visto só por você e pelo RH. O envio de arquivo ainda não está disponível; entregue o comprovante original ao RH."
      />

      <section className="card" aria-labelledby="h-minhas">
        <h2 id="h-minhas" className="section-title">Minhas ausências</h2>
        {mine.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nada por aqui.</p> : (
          <ul className="plain">
            {mine.map((a) => (
              <li key={a.id} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span>{a.kind_label} · {period(a)}</span>
                  <span className={`tag ${a.status}`} style={{ flex: "none" }}>{STATUS[a.status]}</span>
                </div>
                <span className="muted small">{a.reason}{a.decision_note ? ` — Resposta: ${a.decision_note}` : ""}</span>
                {a.status === "pending" && <CancelButton a={a} label="Cancelar pedido" />}
              </li>
            ))}
          </ul>
        )}
      </section>

      {isApprover && others.length > 0 && (
        <section className="card" aria-labelledby="h-outras">
          <h2 id="h-outras" className="section-title">{isHr ? "Ausências da empresa" : "Ausências da equipe"}</h2>
          <ul className="plain">
            {others.map((a) => (
              <li key={a.id} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span><strong>{a.user_name}</strong> · {a.kind_label} · {period(a)}</span>
                  <span className={`tag ${a.status}`} style={{ flex: "none" }}>{STATUS[a.status]}</span>
                </div>
                <span className="muted small">{a.restricted ? "Motivo restrito ao RH" : a.reason}</span>
                {isHr && ["approved", "pending"].includes(a.status) && <CancelButton a={a} label="Cancelar" />}
              </li>
            ))}
          </ul>
        </section>
      )}

      {isHr && (
        <details className="fold">
          <summary>Registrar ausência de um colaborador (RH)</summary>
          <RequestForm
            bare title="" kinds={HR_KINDS} today={today} people={people}
            onDone={() => { notify("ok", "Ausência registrada e já aprovada."); load(); }} onFail={(t) => notify("error", t)}
            note="Registros do RH entram aprovados e ficam na trilha de auditoria. Férias, licenças e afastamentos só o RH registra."
          />
        </details>
      )}
    </>
  );
}

function RequestForm(props: {
  title: string; kinds: [string, string][]; today: string; people?: User[]; note: string; bare?: boolean;
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
    <form className={props.bare ? undefined : "card"} onSubmit={submit}>
      {props.title && <h2 className="section-title">{props.title}</h2>}
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
      <button className="primary" style={{ width: "100%" }} disabled={busy}>{busy ? "Enviando…" : "Enviar"}</button>
    </form>
  );
}
