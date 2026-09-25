import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Kiosk } from "../types";

interface Paired extends Kiosk {
  pairing_code: string;
  pairing_expires_in: number;
}

function ago(iso: string | null): string {
  if (!iso) return "nunca";
  const min = Math.max(0, Math.round((Date.now() - new Date(`${iso}${/Z|[+-]\d\d:\d\d$/.test(iso) ? "" : "Z"}`).getTime()) / 60_000));
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  return min < 1440 ? `há ${Math.round(min / 60)} h` : `há ${Math.round(min / 1440)} d`;
}

function status(k: Kiosk): { label: string; cls: string } {
  if (!k.active) return { label: "Revogada", cls: "rejected" };
  if (k.pairing_pending) return { label: "Aguardando pareamento", cls: "pending" };
  if (!k.paired) return { label: "Sem pareamento", cls: "pending" };
  return { label: "Pareada", cls: "approved" };
}

/** Gestão > Centrais: aparelhos compartilhados onde as pessoas registram o ponto (tela /central). */
export default function Kiosks({ readOnly, notify }: { readOnly: boolean; notify: { ok: (t: string) => void; fail: (e: unknown) => void } }) {
  const { company, user, reload } = useAuth();
  const isAdmin = user?.role === "admin";
  const [list, setList] = useState<Kiosk[]>([]);
  const [fresh, setFresh] = useState<Paired | null>(null); // código de pareamento: aparece só agora
  const [confirm, setConfirm] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", latitude: "", longitude: "", radius: "100" });
  const [geoBusy, setGeoBusy] = useState(false);

  const load = useCallback(() => api<Kiosk[]>("/kiosks").then(setList).catch(notify.fail), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); const t = setInterval(() => void load(), 30_000); return () => clearInterval(t); }, [load]);

  function useMyLocation() {
    if (!navigator.geolocation) return notify.fail(new Error("Este navegador não oferece localização"));
    setGeoBusy(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setForm((f) => ({ ...f, latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6) })); setGeoBusy(false); },
      () => { setGeoBusy(false); notify.fail(new Error("Não foi possível obter a localização (permita o acesso no navegador)")); },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const k = await api<Paired>("/kiosks", {
        method: "POST",
        body: {
          name: form.name, radius_m: Number(form.radius),
          latitude: form.latitude ? Number(form.latitude) : null, longitude: form.longitude ? Number(form.longitude) : null,
        },
      });
      setFresh(k);
      setForm({ name: "", latitude: "", longitude: "", radius: "100" });
      await load();
    } catch (err) {
      notify.fail(err);
    }
  }

  async function repair(k: Kiosk) {
    try {
      setFresh(await api<Paired>(`/kiosks/${k.id}/pairing`, { method: "POST" }));
      setConfirm(null);
      await load();
    } catch (err) {
      notify.fail(err);
    }
  }

  async function revoke(k: Kiosk) {
    try {
      await api(`/kiosks/${k.id}/revoke`, { method: "POST" });
      notify.ok(`${k.name} revogada: o aparelho perdeu o acesso.`);
      setConfirm(null);
      await load();
    } catch (err) {
      notify.fail(err);
    }
  }

  async function togglePin(required: boolean) {
    try {
      await api("/company", { method: "PATCH", body: { kiosk_pin_required: required } });
      await reload();
      notify.ok(required ? "A Central passa a pedir o PIN." : "A Central não pede mais o PIN.");
    } catch (err) {
      notify.fail(err);
    }
  }

  const url = `${window.location.origin}/central`;

  return (
    <>
      {fresh && (
        <div className="alert info" role="status">
          <strong>Código de pareamento de {fresh.name}</strong>
          <div style={{ font: "700 2rem var(--font-display)", letterSpacing: ".2em", margin: "6px 0" }}>{fresh.pairing_code}</div>
          <p className="small" style={{ margin: "0 0 8px" }}>
            No tablet, abra <b>{url}</b> e digite este código. Ele aparece só agora e vale por {Math.round(fresh.pairing_expires_in / 60)} minutos, uma única vez.
          </p>
          <div className="row">
            <button onClick={() => navigator.clipboard?.writeText(fresh.pairing_code)}>Copiar código</button>
            <button className="primary" onClick={() => setFresh(null)}>Fechar</button>
          </div>
        </div>
      )}

      {isAdmin && (
        <section className="card" aria-labelledby="h-pin">
          <h2 id="h-pin" className="section-title">Identificação na Central</h2>
          <label className="check">
            <input type="checkbox" checked={!!company?.kiosk_pin_required} onChange={(e) => void togglePin(e.target.checked)} />
            <span>
              Exigir PIN
              <span className="muted small" style={{ display: "block", fontWeight: 400 }}>
                Desligado (padrão): o código interno ou o CPF sozinho identifica a pessoa, então trate o código como uma senha. Ligado: a pessoa também
                digita o PIN que definiu em Minha conta. O QR do aplicativo, que muda a cada 30 segundos, dispensa o PIN.
              </span>
            </span>
          </label>
          <p className="muted small" style={{ margin: "8px 0 0" }}>A foto é sempre obrigatória na Central. Sem ela, a pessoa usa o aplicativo.</p>
        </section>
      )}

      {list.length === 0 && <p className="muted">Nenhuma central cadastrada.</p>}
      {list.map((k) => {
        const s = status(k);
        return (
          <section className="card" key={k.id}>
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <strong>{k.name}</strong>
              <span className={`tag ${s.cls}`} style={{ flex: "none" }}>{s.label}</span>
            </div>
            <p className="muted small" style={{ margin: "6px 0" }}>
              {k.paired && k.active ? `Vista ${ago(k.last_seen_at)} · ` : ""}
              {k.punches_today ?? 0} batida(s) hoje · raio de {k.radius_m} m ·{" "}
              {k.latitude != null && k.longitude != null ? `posto em ${k.latitude.toFixed(4)}, ${k.longitude.toFixed(4)}` : "posto sem localização"}
            </p>
            {k.active && k.paired && k.last_seen_at && Date.now() - new Date(`${k.last_seen_at}Z`).getTime() > 3_600_000 && (
              <p className="warn small" style={{ margin: "0 0 6px" }}>⚠ Esta central não dá sinal há mais de 1 hora.</p>
            )}
            {isAdmin && k.active && (
              <>
                <div className="row">
                  <button onClick={() => setConfirm(`re-${k.id}`)}>Novo código de pareamento</button>
                  <button className="danger" onClick={() => setConfirm(`rev-${k.id}`)}>Revogar</button>
                </div>
                {confirm === `re-${k.id}` && (
                  <div className="alert info" role="alertdialog" style={{ marginTop: 8 }}>
                    <p style={{ margin: "0 0 8px" }}>Gerar um novo código para {k.name}? O aparelho atual perde o acesso até ser pareado de novo.</p>
                    <div className="row"><button className="primary" onClick={() => repair(k)}>Confirmar</button><button onClick={() => setConfirm(null)}>Voltar</button></div>
                  </div>
                )}
                {confirm === `rev-${k.id}` && (
                  <div className="alert info" role="alertdialog" style={{ marginTop: 8 }}>
                    <p style={{ margin: "0 0 8px" }}>Revogar {k.name}? O aparelho deixa de funcionar na hora. Isso não apaga as batidas já registradas.</p>
                    <div className="row"><button className="danger" onClick={() => revoke(k)}>Confirmar revogação</button><button onClick={() => setConfirm(null)}>Voltar</button></div>
                  </div>
                )}
              </>
            )}
          </section>
        );
      })}

      {isAdmin && (
        <details className="fold">
          <summary>Cadastrar uma central</summary>
          <form className="card" onSubmit={create}>
            <label>Nome do aparelho<input required minLength={2} maxLength={100} placeholder="Ex.: CT-01 Recepção" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <p className="section-title">Posto (onde o tablet fica)</p>
            <div className="grid2 keep">
              <label>Latitude<input inputMode="decimal" placeholder="-23.5505" value={form.latitude} onChange={(e) => setForm({ ...form, latitude: e.target.value })} /></label>
              <label>Longitude<input inputMode="decimal" placeholder="-46.6333" value={form.longitude} onChange={(e) => setForm({ ...form, longitude: e.target.value })} /></label>
            </div>
            <button type="button" disabled={geoBusy} onClick={useMyLocation} style={{ marginBottom: 12 }}>{geoBusy ? "Obtendo…" : "Usar minha localização atual"}</button>
            <label>Raio de tolerância (metros)<input type="number" min={10} max={5000} value={form.radius} onChange={(e) => setForm({ ...form, radius: e.target.value })} /></label>
            <p className="muted small">Fora do raio a batida não é bloqueada: só fica sinalizada para o RH. Até 5 centrais ativas por empresa.</p>
            <button className="primary" style={{ width: "100%" }}>Cadastrar e gerar código de pareamento</button>
          </form>
        </details>
      )}
      {readOnly && !isAdmin && <p className="muted small">Somente o administrador cadastra e revoga centrais.</p>}
    </>
  );
}
