import { Fragment, type ReactNode } from 'react';

/**
 * Renders the assistant's answer: paragraphs, bullet/numbered lists, **bold** and simple
 * pipe tables. Built from React elements only (no HTML injection), so model output can
 * never run as markup.
 */
export function MessageText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const L = (k: number) => lines[k] ?? '';
  let i = 0;
  while (i < lines.length) {
    const line = L(i);
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.trim().startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && L(i).trim().startsWith('|')) {
        const cells = L(i).trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head = [], ...body] = rows;
      blocks.push(
        <div key={blocks.length} className="my-2 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr>{head.map((c, j) => <th key={j} className="border-b border-gray-200 px-2 py-1 font-semibold">{inline(c)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, k) => (
                <tr key={k} className="border-b border-gray-100">
                  {r.map((c, j) => <td key={j} className="px-2 py-1 tabular-nums">{inline(c)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const bullet = /^\s*([-*•]|\d+[.)])\s+/;
    if (bullet.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && bullet.test(L(i))) {
        items.push(L(i).replace(bullet, ''));
        i++;
      }
      const List = ordered ? 'ol' : 'ul';
      blocks.push(
        <List key={blocks.length} className={`my-1.5 space-y-0.5 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}>
          {items.map((it, k) => <li key={k}>{inline(it)}</li>)}
        </List>,
      );
      continue;
    }
    const heading = /^#{1,4}\s+/.test(line);
    const para: string[] = [];
    while (i < lines.length && L(i).trim() && !bullet.test(L(i)) && !L(i).trim().startsWith('|')) {
      para.push(L(i).replace(/^#{1,4}\s+/, ''));
      i++;
      if (heading) break;
    }
    blocks.push(
      <p key={blocks.length} className={heading ? 'mt-2 font-semibold' : 'my-1.5'}>
        {para.map((p, k) => <Fragment key={k}>{k > 0 && <br />}{inline(p)}</Fragment>)}
      </p>,
    );
  }
  return <div className="break-words text-sm leading-relaxed">{blocks}</div>;
}

function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, k) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={k} className="rounded bg-gray-100 px-1">{part.slice(1, -1)}</code>;
    return part;
  });
}
