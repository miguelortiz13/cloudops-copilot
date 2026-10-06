import type { ReactNode } from 'react';

/**
 * Markdown mínimo para las respuestas de los agentes: encabezados, listas,
 * tablas, **negrita** y `código`. El texto se inserta como nodos de texto de
 * React, nunca como HTML, así que una respuesta del modelo no puede inyectar
 * marcado.
 */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // Cursiva solo con delimitadores en límite de palabra: rg_dev_x no es énfasis.
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|(?<![\w*])\*[^*\s][^*]*\*(?![\w*])|(?<!\w)_[^_\s][^_]*_(?!\w))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith('**')) out.push(<strong key={`${keyBase}-${i++}`}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('`')) out.push(<code key={`${keyBase}-${i++}`}>{token.slice(1, -1)}</code>);
    else out.push(<em key={`${keyBase}-${i++}`}>{token.slice(1, -1)}</em>);
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n');
  const blocks: ReactNode[] = [];
  let list: ReactNode[] = [];
  let table: string[][] = [];

  const flushList = (k: number) => {
    if (list.length) blocks.push(<ul key={`ul-${k}`}>{list}</ul>);
    list = [];
  };
  const flushTable = (k: number) => {
    if (!table.length) return;
    const [head, ...rows] = table;
    blocks.push(
      <div className="table-wrap" key={`tb-${k}`}>
        <table className="table">
          <thead><tr>{head.map((h, i) => <th key={i}>{inline(h, `th${k}${i}`)}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>{r.map((c, ci) => <td key={ci}>{inline(c, `td${k}${ri}${ci}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    table = [];
  };

  lines.forEach((raw, k) => {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (trimmed.startsWith('|')) {
      flushList(k);
      if (/^\|[\s:|-]+\|$/.test(trimmed)) return; // separador
      table.push(trimmed.split('|').slice(1, -1).map((c) => c.trim()));
      return;
    }
    flushTable(k);
    if (/^[-•]\s+/.test(trimmed) || /^\*\s+/.test(trimmed)) {
      list.push(<li key={`li-${k}`}>{inline(trimmed.replace(/^[-•*]\s+/, ''), `li${k}`)}</li>);
      return;
    }
    flushList(k);
    if (!trimmed) return;
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      blocks.push(<h3 key={`h-${k}`}>{inline(heading[2], `h${k}`)}</h3>);
      return;
    }
    blocks.push(<p key={`p-${k}`}>{inline(trimmed, `p${k}`)}</p>);
  });
  flushList(lines.length);
  flushTable(lines.length);
  return <>{blocks}</>;
}
