import { useEffect, useRef, useState } from "react";

const MAX_SIDE = 640;
const START_TIMEOUT_MS = 6000;

/** Foto opcional da batida. Devolve o JPEG em base64 (sem prefixo) ou null: qualquer impedimento vira "sem foto", nunca bloqueia. */
export default function CameraCapture({ onDone }: { onDone: (photo: string | null, why?: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const finished = useRef(false);

  const finish = (photo: string | null, why?: string) => {
    if (finished.current) return;
    finished.current = true;
    stream.current?.getTracks().forEach((t) => t.stop());
    onDone(photo, why);
  };

  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => finish(null, "A câmera demorou a responder."), START_TIMEOUT_MS);
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
      .catch(() => finish(null, "Não foi possível usar a câmera."));
    return () => {
      alive = false;
      clearTimeout(timer);
      stream.current?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function shoot() {
    const v = video.current;
    if (!v || !v.videoWidth) return finish(null, "A câmera não entregou imagem.");
    const scale = Math.min(1, MAX_SIDE / Math.max(v.videoWidth, v.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(v.videoWidth * scale);
    canvas.height = Math.round(v.videoHeight * scale);
    canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.7);
    finish(url.split(",", 2)[1] ?? null, url.startsWith("data:image/jpeg") ? undefined : "Este aparelho não gerou a foto.");
  }

  return (
    <section className="card camera" aria-labelledby="h-cam">
      <h2 id="h-cam" className="section-title">Foto da batida (opcional)</h2>
      <video ref={video} playsInline muted aria-label="Prévia da câmera" />
      <button className="primary punch-btn" style={{ minHeight: 64 }} disabled={!ready} onClick={shoot}>
        {ready ? "Tirar foto e registrar" : "Abrindo a câmera…"}
      </button>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="link" onClick={() => finish(null)}>Registrar sem foto</button>
      </div>
    </section>
  );
}
