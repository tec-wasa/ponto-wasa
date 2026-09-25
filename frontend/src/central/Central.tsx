import { useCallback, useEffect, useRef, useState } from "react";
import "./central.css";
import { QueueItem, enqueue, isFinalRejection, loadQueue, remove } from "./offlineQueue";
import { type Method, clockText, friendly, hideDigits, looksLikePontoQr, maskCpf, onlyDigits, validIdentifier, validPin, WedgeBuffer } from "./helpers";
import { Scanner, PhotoStep } from "./media";
import {
  type Identified, KioskApiError, type KioskState, type PunchResult, consentPhoto, getState, getToken, identify, offlinePunch, pair, punch, setToken,
} from "./kioskApi";

const STATE_KEY = "ponto.kiosk.state";

type Screen = "loading" | "unpaired" | "idle" | "qr" | "code" | "pin" | "consent" | "confirm" | "photo" | "sending" | "done" | "error";

const IDLE_MS = 30_000;
const RETURN_MS = 8_000;
const INTERACTIVE: Screen[] = ["qr", "code", "pin", "consent", "confirm", "photo"];

function Keypad({ onDigit, onBack, onOk, okLabel = "OK" }: { onDigit: (d: string) => void; onBack: () => void; onOk: () => void; okLabel?: string }) {
  return (
    <div className="c-pad" role="group" aria-label="Teclado numérico">
      {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((k) => <button key={k} className="c-key" onClick={() => onDigit(k)}>{k}</button>)}
      <button className="c-key act" onClick={onBack} aria-label="Apagar">⌫</button>
      <button className="c-key" onClick={() => onDigit("0")}>0</button>
      <button className="c-key act" onClick={onOk}>{okLabel}</button>
    </div>
  );
}

function Steps({ at }: { at: 1 | 2 | 3 }) {
  const cls = (n: number) => (n < at ? "done" : n === at ? "on" : "");
  return (
    <div className="c-steps" aria-label={`Etapa ${at} de 3`}>
      <span className={cls(1)}>1 Identificar{at > 1 ? " ✓" : ""}</span><span className={cls(2)}>2 Confirmar{at > 2 ? " ✓" : ""}</span><span className={cls(3)}>3 Foto</span>
    </div>
  );
}

export default function Central() {
  const [screen, setScreen] = useState<Screen>("loading");
  const [st, setSt] = useState<KioskState | null>(null);
  const [skew, setSkew] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [online, setOnline] = useState(navigator.onLine);
  const [mode, setMode] = useState<Method>("code");
  const [digits, setDigits] = useState("");
  const [hidden, setHidden] = useState(false);
  const [pin, setPin] = useState("");
  const [pending, setPending] = useState<{ method: "qr" | Method; value: string } | null>(null);
  const [who, setWho] = useState<Identified | null>(null);
  const [result, setResult] = useState<PunchResult | null>(null);
  const [error, setError] = useState("");
  const [pairCode, setPairCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [offQr, setOffQr] = useState<string | null>(null); // batida sem internet em andamento: só o QR do crachá impresso
  const [queued, setQueued] = useState(false);
  const [pendingCount, setPendingCount] = useState(() => loadQueue().length);
  const geo = useRef<Promise<{ lat: number; lon: number } | null>>(Promise.resolve(null));

  const home = useCallback((message = "") => {
    setScreen("idle");
    setDigits(""); setPin(""); setPending(null); setWho(null); setResult(null); setError(""); setBusy(false); setOffQr(null); setQueued(false);
    setNote(message);
  }, []);

  const loadState = useCallback(async () => {
    if (!getToken()) return setScreen("unpaired");
    try {
      const s = await getState();
      setSt(s);
      const sk = new Date(s.server_time).getTime() - Date.now();
      setSkew(sk);
      try { localStorage.setItem(STATE_KEY, JSON.stringify({ s, sk })); } catch { /* sem armazenamento */ }
      setScreen((cur) => (cur === "loading" || cur === "unpaired" ? "idle" : cur));
    } catch (e) {
      if (e instanceof KioskApiError && e.status === 401) {
        setToken(null);
        setNote("Este aparelho não está mais autorizado. Peça um novo pareamento ao administrador.");
        setScreen("unpaired");
      } else if (e instanceof KioskApiError && e.status === 0) {
        try { // sem rede: usa o último estado conhecido (posto, política, desvio do relógio) para a batida sem internet
          const c = JSON.parse(localStorage.getItem(STATE_KEY) ?? "null");
          if (c?.s) { setSt((cur) => cur ?? c.s); setSkew((cur) => cur || c.sk); }
        } catch { /* cache ilegível: fica sem offline */ }
        setScreen((cur) => (cur === "loading" ? "idle" : cur)); // sem rede na abertura: fica na espera, com o aviso
      }
    }
  }, []);

  useEffect(() => {
    void loadState();
    const t = setInterval(() => void loadState(), 5 * 60_000); // detecta revogação e mudança de política
    const clock = setInterval(() => setNow(Date.now()), 1000);
    const on = () => { setOnline(true); void loadState(); };
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { clearInterval(t); clearInterval(clock); window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, [loadState]);

  // envia a fila da Central sem internet quando a rede volta; cada batida é conferida no servidor (QR, prazo, consentimento, sequência)
  const syncing = useRef(false);
  const sync = useCallback(async () => {
    if (syncing.current || !navigator.onLine || !getToken()) return;
    syncing.current = true;
    try {
      for (const item of loadQueue()) {
        try {
          await offlinePunch(item);
          remove(item.key);
        } catch (e) {
          if (e instanceof KioskApiError && isFinalRejection(e.status)) remove(item.key); // recusada: já está na auditoria e no relatório de divergências
          else break; // rede/servidor: tenta de novo depois, na mesma ordem
        }
      }
    } finally {
      syncing.current = false;
      setPendingCount(loadQueue().length);
    }
  }, []);
  useEffect(() => {
    void sync();
    const t = setInterval(() => void sync(), 20_000);
    window.addEventListener("online", sync);
    return () => { clearInterval(t); window.removeEventListener("online", sync); };
  }, [sync]);

  // manter a tela ligada (quando o aparelho permite)
  useEffect(() => {
    let lock: { release: () => Promise<void> } | null = null;
    const ask = async () => {
      try {
        lock = await (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<{ release: () => Promise<void> }> } }).wakeLock?.request("screen") ?? null;
      } catch {
        lock = null;
      }
    };
    void ask();
    const vis = () => document.visibilityState === "visible" && void ask();
    document.addEventListener("visibilitychange", vis);
    return () => { document.removeEventListener("visibilitychange", vis); void lock?.release(); };
  }, []);

  // volta sozinha ao início: 30 s sem toque nas telas interativas; 8 s depois de registrar ou de um erro
  useEffect(() => {
    if (!INTERACTIVE.includes(screen)) return;
    let t = setTimeout(() => home("Tempo esgotado. Comece de novo."), IDLE_MS);
    const reset = () => { clearTimeout(t); t = setTimeout(() => home("Tempo esgotado. Comece de novo."), IDLE_MS); };
    window.addEventListener("pointerdown", reset);
    window.addEventListener("keydown", reset);
    return () => { clearTimeout(t); window.removeEventListener("pointerdown", reset); window.removeEventListener("keydown", reset); };
  }, [screen, home]);
  useEffect(() => {
    if (screen !== "done" && screen !== "error") return;
    const t = setTimeout(() => home(), RETURN_MS);
    return () => clearTimeout(t);
  }, [screen, home]);

  // leitor USB/Bluetooth em modo teclado: na espera ou na tela do QR, uma leitura rápida de um QR do Ponto identifica a pessoa
  const wedge = useRef(new WedgeBuffer());
  const canStartRef = useRef(false);
  useEffect(() => {
    if (screen !== "idle" && screen !== "qr") return;
    const onKey = (e: KeyboardEvent) => {
      const text = wedge.current.feed(e.key, e.timeStamp);
      if (text === null || !canStartRef.current) return;
      if (looksLikePontoQr(text)) { e.preventDefault(); handleQr(text.trim()); }
      else setNote("Código não reconhecido. Use o crachá do Ponto.");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

  // o CPF/código digitado some da tela depois de 3 s parado (só os 3 últimos dígitos ficam)
  useEffect(() => {
    setHidden(false);
    if (screen !== "code" || !digits) return;
    const t = setTimeout(() => setHidden(true), 3000);
    return () => clearTimeout(t);
  }, [digits, screen]);

  const fail = (e: unknown) => {
    const err = e instanceof KioskApiError ? e : new KioskApiError(0, "Erro inesperado");
    if (err.status === 401 && !err.code && screen === "unpaired") return;
    setError(friendly(err.status, err.message, err.code));
    setBusy(false);
    setScreen("error");
  };

  async function runIdentify(method: "qr" | Method, value: string, pinValue?: string) {
    setBusy(true);
    try {
      const w = await identify(method, value, pinValue);
      setWho(w);
      setPending(null);
      setPin("");
      setScreen(w.needs_consent ? "consent" : "confirm");
      setBusy(false);
    } catch (e) {
      if (e instanceof KioskApiError && e.code === "pin_required") {
        setPending({ method, value });
        setPin("");
        setBusy(false);
        setScreen("pin");
      } else if (e instanceof KioskApiError && e.status === 0 && method === "qr" && offlineOk && value.startsWith("PB1.")) {
        setBusy(false);
        offlineScan(value); // o servidor não respondeu: segue como batida sem internet
      } else {
        fail(e);
      }
    }
  }

  function submitCode() {
    const value = onlyDigits(digits);
    if (!validIdentifier(mode, value)) return;
    if (st?.pin_required) { setPending({ method: mode, value }); setPin(""); setScreen("pin"); } // o PIN vem ANTES do nome
    else void runIdentify(mode, value);
  }

  async function agree() {
    if (!who) return;
    setBusy(true);
    try {
      await consentPhoto(who.ticket);
      setBusy(false);
      setScreen("confirm");
    } catch (e) {
      fail(e);
    }
  }

  function offlineScan(text: string) {
    const qr = text.trim();
    if (!qr.startsWith("PB1.")) { setNote("Sem internet só vale o QR do crachá impresso. O QR do aplicativo precisa de conexão."); home("Sem internet só vale o QR do crachá impresso. O QR do aplicativo precisa de conexão."); return; }
    setOffQr(qr);
    startPhoto();
  }

  function handleQr(text: string) {
    if (!navigator.onLine && offlineOk) offlineScan(text);
    else void runIdentify("qr", text);
  }

  function startPhoto() {
    geo.current = new Promise((resolve) => {
      if (!navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }), () => resolve(null),
        { enableHighAccuracy: true, timeout: 5000, maximumAge: 60_000 },
      );
    });
    setScreen("photo");
  }

  async function sendPunch(photo: string) {
    if (offQr) {
      const g = await geo.current;
      const item: QueueItem = {
        key: crypto.randomUUID(), qr: offQr, photo, occurred_at: new Date(Date.now() + skew).toISOString(),
        device_time: new Date().toISOString(), skew_ms: skew, latitude: g?.lat, longitude: g?.lon,
      };
      if (!enqueue(item)) { setError("A memória da central para batidas sem internet está cheia. Use o aplicativo ou procure o RH."); setScreen("error"); return; }
      setPendingCount(loadQueue().length);
      setQueued(true);
      setScreen("done");
      return;
    }
    if (!who) return;
    setScreen("sending");
    try {
      const g = await geo.current;
      setResult(await punch(who.ticket, photo, g?.lat, g?.lon));
      setScreen("done");
    } catch (e) {
      fail(e);
    }
  }

  const photoFailed = useCallback((why: string) => {
    setError(`${why} Nesta central a foto é obrigatória: use o aplicativo ou procure o RH.`);
    setScreen("error");
  }, []);
  const qrFailed = useCallback((why: string) => {
    setError(`${why} Use o código ou o CPF.`);
    setScreen("error");
  }, []);
  const onQr = useCallback((text: string) => { handleQr(text); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function doPair() {
    setBusy(true);
    try {
      const r = await pair(pairCode.trim());
      setToken(r.token);
      setPairCode("");
      setNote("");
      setBusy(false);
      await loadState();
    } catch (e) {
      setBusy(false);
      setNote(e instanceof KioskApiError ? e.message : "Erro ao parear");
    }
  }

  const tz = st?.timezone ?? "America/Sao_Paulo";
  const shown = new Date(now + skew);
  const total = who ? (who.has_break ? 4 : 2) : 4;
  const offlineOk = !!st?.offline?.enabled;
  const offlineMode = !online && offlineOk;
  const canStart = (online && !!st) || offlineMode;
  canStartRef.current = canStart;

  return (
    <div className="central">
      <header className="c-top">
        <div className="c-brand">Ponto<small>Central{st ? ` · ${st.kiosk.name}` : ""}{st ? ` · ${st.company}` : ""}</small></div>
        <div className="c-status">
          <span className={`c-pill ${online ? "" : "bad"}`}>{online ? "Conectada" : "Sem conexão"}</span>
          {st && online && <span className="c-pill">Hora sincronizada</span>}
          {pendingCount > 0 && <span className="c-pill warn">{pendingCount} batida(s) aguardando envio</span>}
        </div>
      </header>

      <main className="c-main" aria-live="polite">
        {screen === "loading" && <p className="c-sub">Carregando…</p>}

        {screen === "unpaired" && (
          <>
            <h1 className="c-title">Parear esta central</h1>
            <p className="c-sub">O administrador gera um código em Gestão → Centrais. Digite-o aqui (vale por 15 minutos).</p>
            <input className="c-input" value={pairCode} maxLength={8} autoCapitalize="characters" autoComplete="off" aria-label="Código de pareamento"
              onChange={(e) => setPairCode(e.target.value.toUpperCase())} />
            {note && <div className="c-alert" role="alert">{note}</div>}
            <div className="c-actions"><button className="c-btn" disabled={busy || pairCode.trim().length < 6} onClick={doPair}>{busy ? "Pareando…" : "Parear"}</button></div>
          </>
        )}

        {screen === "idle" && (
          <>
            <div className="c-clock" role="timer" aria-label="Hora atual">{clockText(now + skew, tz)}</div>
            <div className="c-date">{shown.toLocaleDateString("pt-BR", { timeZone: tz, weekday: "long", day: "numeric", month: "long" })}</div>
            {note && <div className="c-alert" role="status">{note}</div>}
            {!online && !offlineMode && <div className="c-alert" role="alert">Sem conexão: a central precisa de internet para registrar. Use o aplicativo enquanto isso.</div>}
            {offlineMode && <div className="c-alert" role="status">Sem internet: só vale o QR do crachá impresso. A batida fica guardada e é confirmada quando a conexão voltar.</div>}
            <div className="c-actions">
              <button className="c-btn" disabled={!canStart} onClick={() => { setNote(""); setScreen("qr"); }}>Aproxime o QR Code do crachá</button>
              <button className="c-btn ghost" disabled={!canStart || offlineMode} onClick={() => { setNote(""); setMode("code"); setDigits(""); setScreen("code"); }}>Digitar código ou CPF</button>
            </div>
            <p className="c-hint">Toque em uma opção para começar · a tela volta a esta página sozinha</p>
          </>
        )}

        {screen === "qr" && (
          <>
            <Steps at={1} />
            <Scanner onResult={onQr} onFail={qrFailed} />
            <h1 className="c-title">Mostre seu QR Code</h1>
            <p className="c-sub">Use o crachá impresso ou o QR do aplicativo (Ponto → Meu crachá).</p>
            <div className="c-actions">
              <button className="c-btn small ghost" onClick={() => { setMode("code"); setDigits(""); setScreen("code"); }}>Digitar código ou CPF</button>
              <button className="c-btn small ghost" onClick={() => home()}>Cancelar</button>
            </div>
          </>
        )}

        {screen === "code" && (
          <div className="c-cols">
            <div>
              <Steps at={1} />
              <div className="c-seg" role="group" aria-label="Como se identificar">
                <button className={mode === "code" ? "on" : ""} aria-pressed={mode === "code"} onClick={() => { setMode("code"); setDigits(""); }}>Código interno</button>
                <button className={mode === "cpf" ? "on" : ""} aria-pressed={mode === "cpf"} onClick={() => { setMode("cpf"); setDigits(""); }}>CPF</button>
              </div>
              <div className="c-display" aria-live="polite">{digits ? (hidden ? hideDigits(digits) : mode === "cpf" ? maskCpf(digits) : digits) : " "}</div>
              <p className="c-hint">{mode === "cpf" ? "CPF com 11 números" : "Código de 4 a 8 números do seu crachá"}</p>
            </div>
            <div>
              <Keypad onDigit={(d) => setDigits((v) => (v.length < (mode === "cpf" ? 11 : 8) ? v + d : v))} onBack={() => setDigits((v) => v.slice(0, -1))}
                onOk={submitCode} okLabel="Continuar" />
              <div className="c-actions"><button className="c-btn small ghost" onClick={() => home()}>Cancelar</button></div>
            </div>
          </div>
        )}

        {screen === "pin" && (
          <div className="c-cols">
            <div>
              <Steps at={2} />
              <h1 className="c-title">Digite seu PIN</h1>
              <p className="c-sub">Você definiu o PIN em Minha conta, no aplicativo.</p>
              <div className="c-pin" aria-label={`${pin.length} dígitos digitados`}>{Array.from({ length: Math.max(4, pin.length) }, (_, i) => <i key={i} className={i < pin.length ? "f" : ""} />)}</div>
            </div>
            <div>
              <Keypad onDigit={(d) => setPin((v) => (v.length < 6 ? v + d : v))} onBack={() => setPin((v) => v.slice(0, -1))}
                onOk={() => pending && validPin(pin) && !busy && void runIdentify(pending.method, pending.value, pin)} okLabel={busy ? "…" : "Confirmar"} />
              <div className="c-actions"><button className="c-btn small ghost" onClick={() => home()}>Cancelar</button></div>
            </div>
          </div>
        )}

        {screen === "consent" && who && (
          <>
            <Steps at={2} />
            <h1 className="c-title">Olá, {who.first_name}</h1>
            <div className="c-consent">{st?.consent_text}</div>
            <div className="c-actions">
              <button className="c-btn" disabled={busy} onClick={agree}>Concordo e continuar</button>
              <button className="c-btn ghost" onClick={() => home("Sem a autorização da foto, use o aplicativo para registrar o ponto.")}>Não concordo</button>
            </div>
          </>
        )}

        {screen === "confirm" && who && (
          <>
            <Steps at={2} />
            <div className="c-avatar" aria-hidden="true">{who.first_name.slice(0, 1).toUpperCase()}</div>
            <h1 className="c-title">{who.first_name}</h1>
            <div className="c-next"><span>Próxima batida:</span><span>{who.sequence}ª · {who.next_label}</span></div>
            <div className="c-actions">
              <button className="c-btn" onClick={startPhoto}>Registrar e tirar foto</button>
              <button className="c-btn ghost" onClick={() => home()}>Não sou {who.first_name}</button>
            </div>
            <p className="c-hint">Sua foto ajuda o RH a conferir o registro e é apagada quando o mês é fechado.</p>
          </>
        )}

        {screen === "photo" && (
          <>
            <Steps at={3} />
            <PhotoStep onCapture={(p) => void sendPunch(p)} onFail={photoFailed} />
            <p className="c-sub">Olhe para a câmera. A foto é tirada em 3 segundos.</p>
          </>
        )}

        {screen === "sending" && <p className="c-title">Registrando…</p>}

        {screen === "done" && queued && (
          <>
            <div className="c-check" aria-hidden="true">✓</div>
            <h1 className="c-title">Batida guardada</h1>
            <p className="c-sub">Sem internet agora: a batida e a foto foram guardadas neste aparelho e serão confirmadas quando a conexão voltar. Se algo for recusado, o RH avisa.</p>
            <div className="c-actions"><button className="c-btn small" onClick={() => home()}>Concluir</button></div>
            <div className="c-bar" />
          </>
        )}

        {screen === "done" && result && (
          <>
            <div className="c-check" aria-hidden="true">✓</div>
            <h1 className="c-title">Batida registrada às {result.time_local}</h1>
            <p className="c-sub">{result.first_name} · {result.label}{who ? ` · ${who.sequence}ª batida de ${total}` : ""}</p>
            <p className="c-receipt">NSR <b>{result.nsr}</b> · código <code>{result.hash_short}</code> · foto anexada · comprovante no aplicativo (Registros)</p>
            <div className="c-actions"><button className="c-btn small" onClick={() => home()}>Concluir</button></div>
            <div className="c-bar" />
          </>
        )}

        {screen === "error" && (
          <>
            <div className="c-check err" aria-hidden="true">!</div>
            <h1 className="c-title">Não foi possível continuar</h1>
            <p className="c-sub" role="alert">{error}</p>
            <div className="c-actions"><button className="c-btn" onClick={() => home()}>Voltar ao início</button></div>
          </>
        )}
      </main>

      <footer className="c-foot">
        <span>{st ? `Aparelho ${st.kiosk.name} · cada pessoa se identifica antes de cada batida` : "Aparelho não pareado"}</span>
        <button onClick={() => void document.documentElement.requestFullscreen?.().catch(() => undefined)}>Tela cheia</button>
      </footer>
    </div>
  );
}
