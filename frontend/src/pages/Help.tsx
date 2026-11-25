import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { GROUPS, TOPICS, type Block, type Topic } from "../help/content";

/** "**negrito**" vira <b>. */
function rich(text: string): ReactNode {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : <Fragment key={i}>{part}</Fragment>));
}

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function topicText(t: Topic): string {
  const parts = [t.title, t.summary, t.who, t.group];
  for (const b of t.blocks) parts.push(b.h ?? "", b.text ?? "", b.tip ?? "", b.warn ?? "", ...(b.steps ?? []), ...(b.list ?? []));
  return fold(parts.join(" ").replace(/\*\*/g, ""));
}

function BlockView({ b }: { b: Block }) {
  return (
    <>
      {b.h && <h3 className="help-h">{b.h}</h3>}
      {b.text && <p>{rich(b.text)}</p>}
      {b.steps && <ol className="help-steps">{b.steps.map((s, i) => <li key={i}>{rich(s)}</li>)}</ol>}
      {b.list && <ul className="help-list">{b.list.map((s, i) => <li key={i}>{rich(s)}</li>)}</ul>}
      {b.tip && <p className="help-note tip"><b>Dica: </b>{rich(b.tip)}</p>}
      {b.warn && <p className="help-note warn-note"><b>Atenção: </b>{rich(b.warn)}</p>}
    </>
  );
}

/** Ajuda: o manual do aplicativo. Para quem entrou, começa pelos tópicos das funções da pessoa; "Tudo" mostra o manual inteiro. */
export default function Help() {
  const { user, can } = useAuth();
  const location = useLocation();
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState(!!user);
  const [open, setOpen] = useState<Set<string>>(() => new Set(location.hash ? [location.hash.slice(1)] : []));
  const printing = useRef(false);

  const index = useMemo(() => new Map(TOPICS.map((t) => [t.id, topicText(t)])), []);
  const relevant = (t: Topic) => !user || !t.need?.length || t.need.some((p) => can(p));
  const q = fold(query.trim());
  const shown = TOPICS.filter((t) => (!mine || relevant(t)) && (!q || q.split(/\s+/).every((w) => index.get(t.id)!.includes(w))));
  const groups = GROUPS.map((g) => ({ g, items: shown.filter((t) => t.group === g) })).filter((x) => x.items.length);

  // Link direto (#tópico): abre e rola até ele.
  useEffect(() => {
    const id = location.hash.slice(1);
    if (!id) return;
    setOpen((s) => new Set(s).add(id));
    if (!shown.some((t) => t.id === id)) setMine(false);
    requestAnimationFrame(() => document.getElementById(`t-${id}`)?.scrollIntoView({ block: "start" }));
  }, [location.hash]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: string, isOpen: boolean) => {
    if (printing.current) return;
    setOpen((s) => {
      const n = new Set(s);
      if (isOpen) n.add(id);
      else n.delete(id);
      return n;
    });
  };

  function printAll() {
    printing.current = true;
    setOpen(new Set(shown.map((t) => t.id)));
    setTimeout(() => { window.print(); printing.current = false; }, 100);
  }

  return (
    <div className="help">
      <h1 style={{ marginBottom: 4 }}>Ajuda</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        O manual do aplicativo: onde fica cada coisa, para que serve e como fazer, passo a passo.
        {user ? " Começamos pelo que vale para você; toque em “Tudo” para ver o manual inteiro." : ""}
      </p>

      <div className="help-tools noprint">
        <label className="search" style={{ flex: "1 1 240px", margin: 0 }}>
          <span className="sr-only">Buscar na ajuda</span>
          <input type="search" placeholder="Buscar: ex. esqueci de bater, férias, crachá" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        {user && (
          <div className="seg" role="group" aria-label="Quais tópicos mostrar" style={{ margin: 0 }}>
            <button className={mine ? "on" : ""} aria-pressed={mine} onClick={() => setMine(true)}>Para mim</button>
            <button className={!mine ? "on" : ""} aria-pressed={!mine} onClick={() => setMine(false)}>Tudo</button>
          </div>
        )}
        <button onClick={printAll}>Imprimir</button>
      </div>

      {shown.length === 0 && (
        <p className="card muted">
          Nada encontrado para “{query}”.{mine && user ? <> <button className="link" style={{ padding: 0, minHeight: 0 }} onClick={() => setMine(false)}>Buscar no manual inteiro</button></> : null}
        </p>
      )}

      {!q && shown.length > 0 && (
        <nav className="card help-toc noprint" aria-label="Sumário">
          <h2 className="section-title" style={{ marginTop: 0 }}>Sumário</h2>
          <div className="help-toc-cols">
            {groups.map(({ g, items }) => (
              <div key={g}>
                <b className="small">{g}</b>
                <ul>
                  {items.map((t) => <li key={t.id}><a href={`#${t.id}`} onClick={() => setOpen((s) => new Set(s).add(t.id))}>{t.title}</a></li>)}
                </ul>
              </div>
            ))}
          </div>
        </nav>
      )}

      {groups.map(({ g, items }) => (
        <section key={g} aria-label={g}>
          <h2 className="help-group">{g}</h2>
          {items.map((t) => (
            <details key={t.id} id={`t-${t.id}`} className="card help-topic" open={!!q || open.has(t.id)}
              onToggle={(e) => toggle(t.id, e.currentTarget.open)}>
              <summary>
                <span className="help-title">{t.title}</span>
                <span className="muted small help-sum">{t.summary}</span>
                <span className="tag help-who">{t.who}</span>
              </summary>
              <div className="help-body">
                {t.where && user && (
                  <p className="noprint" style={{ marginTop: 0 }}>
                    <Link to={t.where.path} className="pill">Abrir {t.where.label} →</Link>
                  </p>
                )}
                {t.blocks.map((b, i) => <BlockView key={i} b={b} />)}
                <p className="small noprint" style={{ marginBottom: 0 }}>
                  <a href={`#${t.id}`} onClick={(e) => { e.preventDefault(); void navigator.clipboard?.writeText(`${window.location.origin}/ajuda#${t.id}`); }}>
                    Copiar link deste tópico
                  </a>
                </p>
              </div>
            </details>
          ))}
        </section>
      ))}

      <p className="muted small" style={{ marginTop: 24 }}>
        Não encontrou o que procurava? Fale com o RH ou com a Administração da sua empresa.
        {!user && <> <Link to="/">Voltar para a entrada</Link></>}
      </p>
    </div>
  );
}
