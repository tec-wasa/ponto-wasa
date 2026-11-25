import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Absence, Adjustment } from "../types";
import { absencePeriod } from "./Absences";
import { describeAdjustment } from "./Adjustments";

type Item = { key: string; path: string; who: string; what: string; detail: string; self: boolean; label: string };

/** Gestão > Aprovações: ajustes de marcação e ausências pendentes que esta pessoa pode decidir, numa caixa só. */
export default function Approvals() {
  const { company } = useAuth();
  const tz = company!.timezone;
  const [items, setItems] = useState<Item[] | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [open, setOpen] = useState<{ key: string; approve: boolean } | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [adjs, abs] = await Promise.all([api<Adjustment[]>("/adjustments?status=pending"), api<Absence[]>("/absences?status=pending")]);
      setItems([
        ...adjs.filter((a) => a.can_decide).map((a) => ({
          key: `j${a.id}`, path: `/adjustments/${a.id}/decision`, who: a.user_name ?? `#${a.user_id}`, label: "Ajuste de marcação",
          what: describeAdjustment(a, tz), detail: `“${a.reason}”`, self: !!a.self_decision,
        })),
        ...abs.filter((a) => a.can_decide).map((a) => ({
          key: `b${a.id}`, path: `/absences/${a.id}/decision`, who: a.user_name ?? `#${a.user_id}`, label: a.kind_label,
          what: absencePeriod(a), detail: a.restricted ? "Motivo restrito ao RH (dado de saúde)." : `“${a.reason}”`, self: !!a.self_decision,
        })),
      ]);
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro ao carregar" });
    }
  }, [tz]);
  useEffect(() => { void load(); }, [load]);

  async function decide(it: Item, approve: boolean) {
    try {
      await api(it.path, { method: "POST", body: { approve, note: note.trim() || undefined } });
      setMsg({ type: "ok", text: approve ? "Pedido aprovado." : "Pedido rejeitado." });
      setOpen(null);
      setNote("");
      await load();
    } catch (e) {
      setMsg({ type: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  }

  return (
    <>
      <h1>Aprovações</h1>
      {msg && <p className={`alert ${msg.type}`} role={msg.type === "error" ? "alert" : "status"}>{msg.text}</p>}
      {items && items.length === 0 && <p className="card muted">Nenhum pedido aguardando decisão.</p>}
      {items && items.length > 0 && (
        <section className="card" aria-label="Pedidos pendentes">
          <ul className="plain">
            {items.map((it) => (
              <li key={it.key} className="request">
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <strong>{it.who}</strong>
                  <span className="tag pending" style={{ flex: "none" }}>{it.label}</span>
                </div>
                <span>{it.what}</span>
                <span className="muted small">{it.detail}</span>
                {it.self && (
                  <p className="alert info small" style={{ margin: "6px 0 0" }}>
                    Este pedido é seu, e ninguém mais na empresa pode decidi-lo. Para decidir, escreva uma justificativa: ela fica registrada em destaque na auditoria.
                  </p>
                )}
                {open?.key === it.key ? (
                  <div className="request-actions">
                    <label>{it.self ? "Justificativa (obrigatória)" : open.approve ? "Observação (opcional)" : "Motivo da rejeição (opcional)"}
                      <input value={note} onChange={(e) => setNote(e.target.value)} autoFocus minLength={it.self ? 10 : undefined} />
                    </label>
                    <div className="row">
                      <button className={open.approve ? "primary" : "danger"} disabled={it.self && note.trim().length < 10} onClick={() => decide(it, open.approve)}>
                        {open.approve ? "Confirmar aprovação" : "Confirmar rejeição"}
                      </button>
                      <button onClick={() => { setOpen(null); setNote(""); }}>Voltar</button>
                    </div>
                  </div>
                ) : (
                  <div className="row request-actions">
                    <button className="primary" onClick={() => (it.self ? setOpen({ key: it.key, approve: true }) : decide(it, true))}>Aprovar</button>
                    <button onClick={() => { setOpen({ key: it.key, approve: false }); setNote(""); }}>Rejeitar</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
