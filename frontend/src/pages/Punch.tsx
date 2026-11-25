import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, download } from "../api";
import { useAuth } from "../auth";
import CameraCapture from "../CameraCapture";
import PunchSide from "./PunchSide";
import { Greeting } from "../greeting";
import { type QueuedPunch, canPunchOffline, enqueue, hoursLeft, loadQueue, loadSkew, remove, saveSkew } from "../offline";
import { type Kind, SLOT_LABEL, currentCycle, isDayClosed, nextKind, remainingKinds, situation } from "../sequence";
import { QUEUE_EVENT, notifyQueue, runSync } from "../sync";
import type { Punch as PunchT } from "../types";
import { fmtDateTime, fmtTime, parseUtc } from "../util";

/** 01 = aplicativo mobile (PWA instalado); 02 = navegador. */
const COLLECTOR = window.matchMedia?.("(display-mode: standalone)").matches ? "01" : "02";

function deviceId(): string {
  try {
    let id = localStorage.getItem("ponto.device");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("ponto.device", id);
    }
    return id;
  } catch {
    return "desconhecido";
  }
}

function getPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }),
  );
}

type Coords = { latitude?: number; longitude?: number; accuracy_m?: number };

const hasBreakKey = (uid: number) => `ponto.hasbreak.${uid}`;
const crossesKey = (uid: number) => `ponto.crosses.${uid}`;

interface Row {
  key: string;
  label: string;
  time?: string;
  punch?: PunchT;
  pending?: boolean;
  future?: boolean;
}

export default function Punch({ online }: { online: boolean }) {
  const { user, company, reload } = useAuth();
  const tz = company!.timezone;
  // servidor - aparelho, em ms: o relógio mostrado é o do servidor (a última medida vale também sem internet)
  const [skew, setSkew] = useState(() => loadSkew(localStorage)?.ms ?? 0);
  const [now, setNow] = useState(() => new Date());
  const [punches, setPunches] = useState<PunchT[]>([]);
  const [queue, setQueue] = useState<QueuedPunch[]>(() => (user ? loadQueue(localStorage, user.id) : []));
  const [hasBreak, setHasBreak] = useState(() => {
    try {
      return localStorage.getItem(hasBreakKey(user!.id)) !== "0";
    } catch {
      return true;
    }
  });
  const [appBlocked, setAppBlocked] = useState(false); // política "só a Central"
  const [crosses, setCrosses] = useState(() => {
    try {
      return localStorage.getItem(crossesKey(user!.id)) === "1"; // jornada que pode terminar no dia seguinte; padrão: encerra à meia-noite
    } catch {
      return false;
    }
  });
  const [provisional, setProvisional] = useState<QueuedPunch | null>(null);
  const [maxHours, setMaxHours] = useState(() => loadSkew(localStorage)?.maxHours ?? 72);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [skipGps, setSkipGps] = useState(false);
  const [skipPhoto, setSkipPhoto] = useState(false);
  const [camera, setCamera] = useState<{ explicit?: Kind } | null>(null);
  const attemptKey = useRef<string | null>(null); // mesma chave em novas tentativas => sem marcação duplicada

  const load = useCallback(async () => {
    try {
      setPunches(await api<PunchT[]>("/punches?limit=20"));
    } catch {
      /* mantém o que já está na tela */
    }
  }, []);

  const refreshQueue = useCallback(() => {
    if (user) setQueue(loadQueue(localStorage, user.id));
  }, [user]);

  useEffect(() => {
    load();
    const t0 = Date.now();
    api<{ utc: string; offline?: { enabled: boolean; max_hours: number } }>("/time")
      .then((r) => {
        const ms = parseUtc(r.utc).getTime() - (t0 + Date.now()) / 2;
        setSkew(ms);
        // A medida vale para a hora das marcações sem internet: por isso é guardada com o momento em que foi feita.
        saveSkew(localStorage, { ms, at: Date.now(), enabled: r.offline?.enabled ?? false, maxHours: r.offline?.max_hours ?? 72 });
        setMaxHours(r.offline?.max_hours ?? 72);
      })
      .catch(() => undefined);
    api<{ has_break: boolean; crosses_midnight?: boolean; app_blocked?: boolean }>("/punches/next")
      .then((r) => {
        setHasBreak(r.has_break);
        setAppBlocked(!!r.app_blocked);
        setCrosses(!!r.crosses_midnight);
        try {
          localStorage.setItem(hasBreakKey(user!.id), r.has_break ? "1" : "0"); // vale também sem internet
          localStorage.setItem(crossesKey(user!.id), r.crosses_midnight ? "1" : "0");
        } catch {
          /* ignora */
        }
      })
      .catch(() => undefined);
  }, [load, online, user]);

  useEffect(() => {
    // O envio da fila acontece no App; aqui só se atualiza a tela quando algo mudou.
    const onQueue = () => {
      refreshQueue();
      load();
    };
    window.addEventListener(QUEUE_EVENT, onQueue);
    return () => window.removeEventListener(QUEUE_EVENT, onQueue);
  }, [refreshQueue, load]);

  useEffect(() => {
    // O cartão provisório some quando a marcação sai da fila: foi enviada (ou descartada).
    if (provisional && !queue.some((q) => q.key === provisional.key)) {
      setProvisional(null);
      setNotice("Marcação enviada e registrada. O comprovante está na lista de hoje.");
    }
  }, [queue, provisional]);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date(Date.now() + skew)), 1000);
    return () => clearInterval(t);
  }, [skew]);

  const pending = queue.filter((q) => q.status === "pending");
  const rejected = queue.filter((q) => q.status === "rejected");
  // O que ainda está na fila conta: a próxima marcação segue a última, mesmo a que ainda não foi enviada.
  const lastPending = pending[pending.length - 1];
  const last = lastPending ? { kind: lastPending.kind, occurred_at: lastPending.occurred_at } : punches[0];
  const clockNow = Date.now();
  const rules = { tz, crosses };
  const next: Kind = nextKind(last, hasBreak, clockNow, rules);
  const marks = [...pending].reverse().map((q) => ({ kind: q.kind, occurred_at: q.occurred_at })).concat(punches);
  const closed = isDayClosed(marks, clockNow, rules); // a 4ª batida (saída) é definitiva: não existe quinta
  const sit = situation(last, clockNow, rules);

  // Linha do tempo = o TURNO em andamento (não o dia do calendário): um turno que começou ontem à noite continua inteiro aqui.
  const cycle = currentCycle(marks.map((mk, i) => ({ ...mk, src: i < pending.length ? pending[pending.length - 1 - i] : punches[i - pending.length] })), clockNow, rules);
  const rows: Row[] = cycle.map((c): Row =>
    "id" in c.src
      ? { key: `p${c.src.id}`, label: SLOT_LABEL[c.kind as Kind] ?? c.kind, time: fmtTime(c.occurred_at, tz), punch: c.src }
      : { key: c.src.key, label: SLOT_LABEL[c.kind as Kind] ?? c.kind, time: fmtTime(c.occurred_at, tz), pending: true });
  const future = remainingKinds(cycle.length ? cycle[cycle.length - 1] : undefined, hasBreak, clockNow, rules).map((k, i): Row => ({
    key: `f${i}`, label: SLOT_LABEL[k], future: true,
  }));

  const statusText =
    sit === "working" ? `Trabalhando desde ${fmtTime(last!.occurred_at, tz)}`
      : sit === "break" ? `Em intervalo desde ${fmtTime(last!.occurred_at, tz)}`
        : "Fora do expediente";
  const photoActive = !!company?.photo_enabled && !!user?.photo_consent_at && !!navigator.mediaDevices?.getUserMedia;
  const canSkipBreak = !closed && !appBlocked && hasBreak && next === "inicio_intervalo";

  async function allowGps() {
    try {
      await api("/auth/consent-gps", { method: "POST" });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao registrar consentimento");
    }
  }

  async function downloadReceipt(punchId: number, nsr: number) {
    setError("");
    try {
      await download(`/punches/${punchId}/receipt.pdf`, `comprovante-NSR${nsr}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao baixar o comprovante");
    }
  }

  /** Guarda a marcação no aparelho. Devolve false (com o motivo na tela) se não for possível. */
  function queueOffline(coords: Coords, kind: Kind, photo: string | null): boolean {
    const check = canPunchOffline(loadSkew(localStorage), Date.now());
    if (!check.ok) {
      setError(check.reason);
      return false;
    }
    const item: QueuedPunch = {
      key: attemptKey.current!, kind,
      occurred_at: check.occurredAt.toISOString(), device_time: new Date().toISOString(), skew_ms: Math.round(check.skewMs),
      collector: COLLECTOR, device_id: deviceId(), ...coords, queued_at: new Date().toISOString(), status: "pending",
      ...(photo ? { photo } : {}),
    };
    try {
      enqueue(localStorage, user!.id, item);
    } catch {
      delete item.photo; // sem espaço para a foto: guarda só a batida (a foto é opcional)
      try {
        enqueue(localStorage, user!.id, item);
        photo = null;
        setNotice("A foto não coube no aparelho; a batida foi guardada sem ela.");
      } catch {
        setError("Não foi possível guardar a marcação neste aparelho (armazenamento cheio ou bloqueado). Ela NÃO foi registrada.");
        return false;
      }
    }
    attemptKey.current = null;
    setProvisional(item);
    refreshQueue();
    return true;
  }

  async function sendNow() {
    setError("");
    const r = await runSync(user!.id).catch(() => null);
    if (r?.stopped) setError("Ainda não foi possível enviar. Tentaremos de novo automaticamente.");
    else if (r?.sent) setNotice(`${r.sent} marcação(ões) enviada(s) e registrada(s).`);
  }

  /** `explicit` só é usado para sair sem ter feito o intervalo; nos demais casos a ORDEM decide o tipo. */
  /** Com foto ativada e consentida, abre a câmera antes; sem isso (ou sem câmera) registra direto. */
  function register(explicit?: Kind) {
    if (closed) return;
    if (photoActive) {
      setError("");
      setNotice("");
      setCamera({ explicit });
      return;
    }
    void doRegister(explicit, null);
  }

  async function doRegister(explicit: Kind | undefined, photo: string | null, why = "") {
    if (closed) return;
    setBusy(true);
    setError("");
    setNotice("");
    attemptKey.current ??= crypto.randomUUID();
    const kind = explicit ?? next;
    let coords: Coords = {};
    if (user?.gps_consent_at && "geolocation" in navigator) {
      try {
        const pos = await getPosition();
        coords = { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy_m: pos.coords.accuracy };
      } catch {
        setNotice("Não foi possível obter a localização; o ponto foi registrado sem ela.");
      }
    }
    if (!online) {
      queueOffline(coords, kind, photo);
      setBusy(false);
      return;
    }
    try {
      const p = await api<PunchT>("/punches", {
        method: "POST",
        body: { kind: explicit, client_key: attemptKey.current, device_id: deviceId(), collector: COLLECTOR, ...coords },
      });
      attemptKey.current = null;
      setProvisional(null);
      let photoNote = why ? ` ${why} Registrado sem foto.` : "";
      if (photo) {
        try {
          await api(`/punches/${p.id}/photo`, { method: "POST", body: { image_base64: photo } });
        } catch {
          photoNote = " A foto não foi enviada, mas o registro vale.";
        }
      }
      setNotice(`Registrado: ${SLOT_LABEL[p.kind as Kind] ?? "marcação"} às ${fmtTime(p.occurred_at, tz)}.${photoNote}`);
      await load();
    } catch (e) {
      // A conexão caiu no meio: guarda com a MESMA chave. Se o pedido chegou ao servidor, o reenvio devolve o mesmo registro.
      if (e instanceof ApiError && e.status === 0 && queueOffline(coords, kind, photo)) setNotice("Sem conexão: a marcação foi guardada no aparelho.");
      else setError(e instanceof Error ? e.message : "Erro ao registrar");
    } finally {
      setBusy(false);
    }
  }

  const dateText = now.toLocaleDateString("pt-BR", { timeZone: tz, weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="punch-layout">
      <Greeting name={user?.name ?? ""} tz={tz} />
      <div className="punch-main">
      {camera && (
        <CameraCapture
          onDone={(photo, why) => {
            const explicit = camera.explicit;
            setCamera(null);
            void doRegister(explicit, photo, why ?? "");
          }}
        />
      )}
      <section className="card punch-card noprint" hidden={!!camera} aria-labelledby="h-ponto">
        <h1 id="h-ponto" className="section-title">Registrar ponto</h1>
        <div className="clock" role="timer" aria-label="Hora atual">{now.toLocaleTimeString("pt-BR", { timeZone: tz })}</div>
        <p className="clock-date">{dateText}</p>
        <span className={`status-chip ${sit === "working" ? "" : sit}`} role="status">
          <span className={`dot ${sit}`} aria-hidden="true" />{statusText}
        </span>

        <button className="primary punch-btn" onClick={() => register()} disabled={busy || closed || appBlocked}>
          {closed ? "Jornada encerrada" : busy ? "Registrando…" : "Registrar ponto"}
        </button>
        <p className="punch-next">
          {appBlocked ? (
            "Você registra o ponto na Central do Ponto. Este aplicativo mostra o seu espelho e os seus pedidos."
          ) : closed ? (
            "Todas as batidas de hoje foram registradas. Até a próxima jornada!"
          ) : (
            <>
              Próxima batida: <b>{rows.length + 1}ª · {SLOT_LABEL[next]}</b>
              {!online && " · sem internet: fica guardado e é enviado depois"}
            </>
          )}
        </p>
        {canSkipBreak && (
          <button className="link punch-alt" onClick={() => register("saida")} disabled={busy}>Vou embora sem fazer o intervalo</button>
        )}

        {error && <p className="alert error" role="alert" style={{ marginTop: 12 }}>{error}</p>}
        {notice && <p className="alert ok" role="status" style={{ marginTop: 12 }}>{notice}</p>}
      </section>


      {provisional && (
        <section className="card" role="status" aria-labelledby="h-prov">
          <h2 id="h-prov" style={{ marginTop: 0 }}>Guardado — aguardando envio</h2>
          <p style={{ margin: "0 0 8px" }}>
            <b>{SLOT_LABEL[provisional.kind as Kind]}</b> às {fmtTime(provisional.occurred_at, tz)} · protocolo <code>{provisional.key.slice(0, 8)}</code>
          </p>
          <p className="muted small" style={{ margin: "0 0 8px" }}>
            Ainda <b>não é o comprovante oficial</b>: o NSR e o comprovante saem quando for enviada. Conecte-se à internet em até {maxHours} h.
          </p>
          <button onClick={() => setProvisional(null)}>Fechar</button>
        </section>
      )}

      {(pending.length > 0 || rejected.length > 0) && (
        <section className="card noprint" aria-labelledby="h-fila">
          <h2 id="h-fila" className="section-title">Aguardando envio ({pending.length})</h2>
          <ul className="plain">
            {pending.map((q) => {
              const left = hoursLeft(q, maxHours, Date.now());
              return (
                <li key={q.key}>
                  <span>{SLOT_LABEL[q.kind as Kind]} · {fmtDateTime(q.occurred_at, tz)}</span>
                  <span className={left < 12 ? "warn" : "muted"}>{left > 0 ? `envie em até ${Math.floor(left)} h` : "prazo vencido"}</span>
                </li>
              );
            })}
          </ul>
          {pending.length > 0 && <button disabled={!online} onClick={sendNow}>{online ? "Enviar agora" : "Sem conexão"}</button>}
          {rejected.map((q) => (
            <div key={q.key} className="alert error" role="alert" style={{ marginTop: 12 }}>
              <b>{SLOT_LABEL[q.kind as Kind]} de {fmtDateTime(q.occurred_at, tz)} não foi aceita:</b> {q.error}
              <p className="small" style={{ margin: "4px 0 8px" }}>
                Ela não vale como registro. Se você realmente trabalhou nesse horário, peça a inclusão em <b>Solicitações</b>; seu gestor aprova.
              </p>
              <button onClick={() => { remove(localStorage, user!.id, q.key); refreshQueue(); notifyQueue(); }}>Descartar</button>
            </div>
          ))}
        </section>
      )}

      <section className="card noprint" aria-labelledby="h-hoje">
        <h2 id="h-hoje" className="section-title">Hoje</h2>
        <ul className="timeline">
          {[...rows, ...future].map((r, i) => (
            <li key={r.key} className={r.future ? "future" : r.pending ? "pending" : ""}>
              <span><span className="ord" aria-label={`Batida ${i + 1}`}>{i + 1}</span>{r.label}</span>
              <span className="side">
                <span className="when">{r.time ?? "—"}</span>
                {r.punch && (
                  <button className="link" onClick={() => downloadReceipt(r.punch!.id, r.punch!.nsr)}
                    aria-label={`Baixar comprovante de ${r.label} (NSR ${r.punch.nsr})`}>Comprovante</button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {company?.photo_enabled && !user?.photo_consent_at && !skipPhoto && (
        <div className="alert info noprint" style={{ marginBottom: 14 }}>
          <p className="small" style={{ margin: "0 0 8px" }}>
            Tirar uma foto a cada batida? É opcional. A foto serve só para o RH conferir que foi você, fica guardada com criptografia,
            só o RH e o administrador a veem e ela é apagada quando o mês é fechado. Se a câmera falhar, o ponto é registrado do mesmo jeito.
          </p>
          <div className="row">
            <button className="primary" onClick={async () => { try { await api("/auth/consent-photo", { method: "POST" }); await reload(); } catch (e) { setError(e instanceof Error ? e.message : "Erro"); } }}>Permitir foto</button>
            <button onClick={() => setSkipPhoto(true)}>Agora não</button>
          </div>
        </div>
      )}

      {!user?.gps_consent_at && !skipGps && (
        <div className="alert info noprint" style={{ marginBottom: 14 }}>
          <p className="small" style={{ margin: "0 0 8px" }}>
            Registrar sua localização junto com o ponto? Só é usada para conferência da jornada (LGPD) e você pode recusar.
          </p>
          <div className="row">
            <button className="primary" onClick={allowGps}>Permitir</button>
            <button onClick={() => setSkipGps(true)}>Agora não</button>
          </div>
        </div>
      )}
      </div>
      <PunchSide refreshKey={punches.length + pending.length}
        open={sit === "working" && last ? { since: last.occurred_at, minutes: Math.max(0, Math.floor((clockNow - parseUtc(last.occurred_at).getTime()) / 60_000)) } : undefined} />
    </div>
  );
}
