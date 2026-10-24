// Minimal, safe Markdown renderer for reports we generate ourselves (headings, lists,
// tables, code blocks, bold/italic). Renders React elements only; never injects HTML.

function inline(s: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const t = m[0];
    const k = `${key}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k} className="rounded bg-muted px-1 font-mono text-[0.85em]">{t.slice(1, -1)}</code>);
    else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    const k = `b${i}`;
    if (l.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      blocks.push(<pre key={k} className="overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-5">{body.join("\n")}</pre>);
      i++;
      continue;
    }
    if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
        if (!cells.every((c) => /^[-:]+$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push(
        <div key={k} className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b">{rows[0]?.map((c, j) => <th key={j} className="px-2 py-1.5 text-left font-medium">{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.slice(1).map((r, ri) => <tr key={ri} className="border-b last:border-0">{r.map((c, j) => <td key={j} className="px-2 py-1.5 tabular-nums">{inline(c, `${k}${ri}${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (l.startsWith("- ") || l.startsWith("  - ")) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("  - "))) items.push(lines[i++].replace(/^\s*- /, ""));
      blocks.push(<ul key={k} className="list-disc space-y-1 pl-5">{items.map((t, j) => <li key={j}>{inline(t, `${k}${j}`)}</li>)}</ul>);
      continue;
    }
    if (l.startsWith("# ")) blocks.push(<h2 key={k} className="text-xl font-semibold">{inline(l.slice(2), k)}</h2>);
    else if (l.startsWith("## ")) blocks.push(<h3 key={k} className="pt-2 text-base font-semibold">{inline(l.slice(3), k)}</h3>);
    else if (l.startsWith("### ")) blocks.push(<h4 key={k} className="text-sm font-semibold">{inline(l.slice(4), k)}</h4>);
    else if (l.trim()) blocks.push(<p key={k}>{inline(l.trim(), k)}</p>);
    i++;
  }
  return <div className="space-y-3 text-sm leading-6">{blocks}</div>;
}
