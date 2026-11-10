import type { ReactNode } from 'react'

/**
 * Renders the small Markdown subset policy documents use: paragraphs, bullet and numbered
 * lists, tables, **bold** and *italic*. Builds React elements (never innerHTML), so
 * document text cannot inject markup.
 */
export function MarkdownLite({ text, className = '' }: { text: string; className?: string }) {
  const blocks = text.split(/\n\s*\n/).filter((b) => b.trim())
  return <div className={`grid gap-2 ${className}`}>{blocks.map((b, i) => <Block key={i} block={b} />)}</div>
}

function Block({ block }: { block: string }) {
  const lines = block.split('\n').map((l) => l.trim())
  if (lines.every((l) => l.startsWith('|'))) return <Table lines={lines} />
  if (lines.every((l) => /^[-*]\s/.test(l))) {
    return (
      <ul className="list-disc space-y-0.5 pl-4">
        {lines.map((l, i) => (
          <li key={i}>{inline(l.replace(/^[-*]\s+/, ''))}</li>
        ))}
      </ul>
    )
  }
  if (lines.every((l) => /^\d+\.\s/.test(l))) {
    return (
      <ol className="list-decimal space-y-0.5 pl-4">
        {lines.map((l, i) => (
          <li key={i}>{inline(l.replace(/^\d+\.\s+/, ''))}</li>
        ))}
      </ol>
    )
  }
  return <p>{inline(lines.join(' '))}</p>
}

function Table({ lines }: { lines: string[] }) {
  const rows = lines
    .filter((l) => !/^\|[\s:|-]+\|$/.test(l)) // drop the |---|---| separator
    .map((l) =>
      l
        .replace(/^\||\|$/g, '')
        .split('|')
        .map((c) => c.trim()),
    )
  const [head, ...body] = rows
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-hairline">
            {head.map((c, i) => (
              <th key={i} className="py-1 pr-3 font-semibold text-ink">
                {inline(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i} className="border-b border-hairline last:border-0">
              {r.map((c, j) => (
                <td key={j} className="py-1 pr-3">
                  {inline(c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function inline(text: string): ReactNode[] {
  // Split on **bold** and *italic* while keeping the delimiters' content.
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return (
        <strong key={i} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      )
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>
    return part
  })
}
