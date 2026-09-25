import jsQR from "jsqr";
import { useEffect, useRef, useState } from "react";
import { looksLikePontoQr } from "./helpers";

const START_TIMEOUT_MS = 7000;

/** Abre a câmera frontal. `error` vem preenchido se recusar, faltar câmera ou demorar demais. */
function useCamera() {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => alive && !stream.current && setError("A câmera demorou a responder."), START_TIMEOUT_MS);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Este aparelho não oferece câmera.");
    } else {
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 640 } }, audio: false })
        .then(async (s) => {
          if (!alive) return s.getTracks().forEach((t) => t.stop());
          stream.current = s;
          if (video.current) {
            video.current.srcObject = s;
            await video.current.play().catch(() => undefined);
          }
          clearTimeout(timer);
          setReady(true);
        })
        .catch(() => alive && setError("Não foi possível usar a câmera."));
    }
    return () => {
      alive = false;
      clearTimeout(timer);
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
    };
  }, []);

  return { video, ready, error };
}

/** Lê o QR do crachá. `BarcodeDetector` quando existe; senão `jsQR` sobre quadros reduzidos. Só entrega QR do Ponto. */
export function Scanner({ onResult, onFail }: { onResult: (text: string) => void; onFail: (why: string) => void }) {
  const { video, ready, error } = useCamera();
  const done = useRef(false);
  const [ignored, setIgnored] = useState(false);

  useEffect(() => {
    if (error) onFail(error);
  }, [error, onFail]);

  useEffect(() => {
    if (!ready) return;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const Detector = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => { detect: (v: HTMLVideoElement) => Promise<{ rawValue: string }[]> } }).BarcodeDetector;
    const detector = Detector ? new Detector({ formats: ["qr_code"] }) : null;
    let stop = false;

    const accept = (text: string) => {
      if (done.current) return;
      if (looksLikePontoQr(text)) {
        done.current = true;
        onResult(text.trim());
      } else {
        setIgnored(true);
        setTimeout(() => setIgnored(false), 2500);
      }
    };

    const tick = async () => {
      const v = video.current;
      if (stop || done.current || !v) return;
      try {
        if (v.videoWidth) {
          if (detector) {
            const found = await detector.detect(v);
            if (found[0]) accept(found[0].rawValue);
          } else {
            const scale = Math.min(1, 480 / v.videoWidth);
            canvas.width = Math.round(v.videoWidth * scale);
            canvas.height = Math.round(v.videoHeight * scale);
            ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
            const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const code = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
            if (code) accept(code.data);
          }
        }
      } catch {
        /* quadro ruim: tenta o próximo */
      }
      if (!stop && !done.current) setTimeout(tick, 220);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [ready, video, onResult]);

  return (
    <div className="viewfinder" role="img" aria-label="Câmera lendo o QR Code">
      <video ref={video} playsInline muted />
      <div className="frame" aria-hidden="true" />
      <div className="scanline" aria-hidden="true" />
      {!ready && !error && <p className="vf-msg">Abrindo a câmera…</p>}
      {ignored && <p className="vf-msg warn">Esse QR Code não é do Ponto</p>}
    </div>
  );
}

const MAX_SIDE = 640;

/** Foto da batida: contagem de 3 s e disparo automático. Devolve o JPEG (base64) ou avisa a falha. */
export function PhotoStep({ onCapture, onFail }: { onCapture: (photoBase64: string) => void; onFail: (why: string) => void }) {
  const { video, ready, error } = useCamera();
  const [count, setCount] = useState(3);
  const [flash, setFlash] = useState(false);
  const shot = useRef(false);

  useEffect(() => {
    if (error) onFail(error);
  }, [error, onFail]);

  const shoot = () => {
    const v = video.current;
    if (shot.current) return;
    if (!v || !v.videoWidth) return onFail("A câmera não entregou imagem.");
    shot.current = true;
    const scale = Math.min(1, MAX_SIDE / Math.max(v.videoWidth, v.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(v.videoWidth * scale);
    canvas.height = Math.round(v.videoHeight * scale);
    canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.7);
    if (!url.startsWith("data:image/jpeg")) return onFail("Este aparelho não gerou a foto.");
    setFlash(true);
    setTimeout(() => onCapture(url.split(",", 2)[1]), 350);
  };

  useEffect(() => {
    if (!ready || shot.current) return;
    if (count <= 0) return shoot();
    const t = setTimeout(() => setCount((c) => c - 1), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, count]);

  return (
    <div className="cam">
      <video ref={video} playsInline muted aria-label="Prévia da câmera" />
      {ready && count > 0 && <div className="count" aria-live="polite">{count}</div>}
      {flash && <div className="flash go" />}
      {!ready && !error && <p className="vf-msg">Abrindo a câmera…</p>}
      <button className="btn small photo-now" onClick={shoot} disabled={!ready}>Tirar agora</button>
    </div>
  );
}
