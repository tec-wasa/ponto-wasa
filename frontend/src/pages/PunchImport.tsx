import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";

interface Issue { line: number; person: string; message: string }
interface Result {
  dry_run: boolean; total: number; empty: number; days: number; marks: number; imported: boolean; batch: string | null;
  errors: Issue[]; warnings: Issue[]; skipped: Issue[];
  people: { name: string; days: number; marks: number; first: string; last: string }[];
}
interface Batch { batch: string; active: number; revoked: number; first: string; last: string; at: string; reason: string }

const brDate = (iso: string) => iso.slice(0, 10).split("-").reverse().join("/");

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function IssueTable({ items }: { items: Issue[] }) {
  return (
    <div className="scroll"><table>
      <thead><tr><th>Linha</th><th>Pessoa</th><th>Situação</th></tr></thead>
      <tbody>{items.map((e, i) => <tr key={i}><td>{e.line}</td><td>{e.person}</td><td>{e.message}</td></tr>)}</tbody>
    </table></div>
  );
}

/** Importa marcações de outro sistema de ponto (CSV) como inclusões aprovadas; lista e desfaz importações. */
export default function PunchImportCard() {
  const [file, setFile] = useState<{ name: string; b64: string } | null>(null);
  const [reason, setReason] = useState("Migração do sistema de ponto anterior");
  const [result, setResult] = useState<Result | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [undoing, setUndoing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const loadBatches = useCallback(() => api<Batch[]>("/imports/punches").then(setBatches).catch(() => setBatches([])), []);
  useEffect(() => { void loadBatches(); }, [loadBatches]);

  async function pick(f: File | undefined) {
    setResult(null); setError(""); setMsg("");
    setFile(f ? { name: f.name, b64: toBase64(await f.arrayBuffer()) } : null);
  }

  async function run(dry: boolean) {
    if (!file) return;
    setBusy(true); setError(""); setMsg("");
    try {
      const r = await api<Result>(`/imports/punches?dry_run=${dry}`, { method: "POST", body: { content_base64: file.b64, reason } });
      setResult(r);
      if (r.imported) {
        setMsg(`${r.marks} marcação(ões) de ${r.days} dia(s) importadas como inclusões aprovadas.`);
        void loadBatches();
      }
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === "object" && "errors" in err.data) setResult(err.data as Result);
      else setError(err instanceof Error ? err.message : "Erro");
    } finally {
      setBusy(false);
    }
  }

  async function undo(batch: string) {
    setError(""); setMsg("");
    try {
      const r = await api<{ revoked: number }>(`/imports/punches/${encodeURIComponent(batch)}/undo`, { method: "POST" });
      setMsg(`Importação desfeita: ${r.revoked} inclusão(ões) canceladas.`);
      void loadBatches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro");
    } finally {
      setUndoing(null);
    }
  }

  const ready = !!result && result.dry_run && result.errors.length === 0 && result.days > 0;
  return (
    <section className="card">
      <p className="muted small" style={{ marginTop: 0 }}>
        Traz as batidas de outro sistema como <b>inclusões aprovadas</b>, com o motivo abaixo: aparecem tratadas no Espelho e na folha e vão
        para o AEJ. Pela Portaria 671 elas não viram marcações originais deste ponto: guarde o AFD e os relatórios do sistema anterior.
      </p>
      <p className="muted small">
        Uma linha por pessoa e dia. Colunas: <b>cpf</b>, <b>data</b> (dd/mm/aaaa) e <b>batida_1</b>, <b>batida_2</b>… (HH:MM), ou uma
        coluna <b>batidas</b> com os horários separados por espaço. Outras colunas são ignoradas, assim como linhas sem batidas (folga,
        feriado, férias). Dias que já têm marcações no app ficam de fora. Férias, atestados e saldo de banco de horas se lançam em
        Ausências e em Banco de horas.
      </p>
      <label>Motivo (vai em cada inclusão e na auditoria)
        <input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
      </label>
      <input type="file" accept=".csv,text/csv" aria-label="Arquivo CSV de marcações" onChange={(e) => pick(e.target.files?.[0])} />
      {error && <p className="alert error" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      {msg && <p className="alert ok" role="status" style={{ marginTop: 12 }}>{msg}</p>}
      {file && !result?.imported && (
        <div className="row" style={{ marginTop: 12 }}>
          <button disabled={busy} onClick={() => run(true)}>{busy ? "Validando…" : "Validar arquivo"}</button>
          <button className="primary" disabled={busy || !ready || reason.trim().length < 10} onClick={() => run(false)}>
            {ready ? `Importar ${result!.marks} marcações` : "Importar"}
          </button>
        </div>
      )}

      {result && !result.imported && (
        <div style={{ marginTop: 12 }}>
          {result.errors.length > 0 ? (
            <>
              <p className="alert error" role="alert">{result.errors.length} problema(s). Corrija o arquivo e valide de novo; nada foi gravado.</p>
              <IssueTable items={result.errors} />
            </>
          ) : (
            <p className="alert ok" role="status">
              {result.marks} marcação(ões) de {result.days} dia(s) prontas para importar
              {result.empty ? ` (${result.empty} linha(s) sem batidas ignoradas)` : ""}. Nada foi gravado ainda.
            </p>
          )}
          {result.people.length > 0 && (
            <div className="scroll"><table>
              <thead><tr><th>Pessoa</th><th>Dias</th><th>Marcações</th><th>Período</th></tr></thead>
              <tbody>{result.people.map((p) => (
                <tr key={p.name}><td>{p.name}</td><td>{p.days}</td><td>{p.marks}</td><td>{brDate(p.first)} a {brDate(p.last)}</td></tr>
              ))}</tbody>
            </table></div>
          )}
          {result.skipped.length > 0 && <><p className="section-title">Ficam de fora (já têm marcações no app)</p><IssueTable items={result.skipped} /></>}
          {result.warnings.length > 0 && <><p className="section-title">Avisos (não impedem a importação)</p><IssueTable items={result.warnings} /></>}
        </div>
      )}

      {batches.length > 0 && (
        <>
          <p className="section-title">Importações feitas</p>
          <ul className="plain">
            {batches.map((b) => (
              <li key={b.batch} className="request" style={{ padding: "10px 0" }}>
                <strong>{brDate(b.first)} a {brDate(b.last)} · {b.active} ativa(s){b.revoked ? ` · ${b.revoked} desfeita(s)` : ""}</strong>
                <span className="muted small">{b.reason} · importada em {brDate(b.at)}</span>
                {b.active > 0 && (undoing === b.batch ? (
                  <div className="alert info" role="alertdialog" aria-label="Confirmar desfazer importação" style={{ marginTop: 8 }}>
                    <p style={{ margin: "0 0 8px" }}>
                      Desfazer esta importação? As {b.active} inclusões deixam de valer (a trilha fica na auditoria). Só é possível com o mês aberto.
                    </p>
                    <div className="row"><button className="danger" onClick={() => undo(b.batch)}>Confirmar</button><button onClick={() => setUndoing(null)}>Voltar</button></div>
                  </div>
                ) : (
                  <div className="row" style={{ marginTop: 6 }}><button className="danger" onClick={() => setUndoing(b.batch)}>Desfazer importação</button></div>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
