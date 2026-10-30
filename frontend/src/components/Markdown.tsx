import type { ReactNode } from 'react'
import { parseMarkdown } from '../lib/markdown'
import type { Inline } from '../lib/markdown'

/** Renders chatbot Markdown safely: React escapes every text node, and no HTML string is ever injected. */
function renderInline(nodes: Inline[], key = ''): ReactNode[] {
  return nodes.map((n, i) => {
    const k = `${key}${i}`
    switch (n.t) {
      case 'text': return <span key={k}>{n.v}</span>
      case 'strong': return <strong key={k} className="font-semibold text-ink">{renderInline(n.c, k)}</strong>
      case 'em': return <em key={k}>{renderInline(n.c, k)}</em>
      case 'code': return <code key={k} className="whitespace-pre-wrap rounded bg-emerald-900/5 px-1 py-0.5 font-mono text-[0.85em]">{n.v}</code>
      case 'link': return <a key={k} href={n.href} target="_blank" rel="noopener noreferrer nofollow" className="font-semibold text-emerald-700 underline-offset-2 hover:underline">{renderInline(n.c, k)}</a>
    }
  })
}

export default function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text)
  return (
    <div className="space-y-2 break-words text-sm leading-relaxed">
      {blocks.map((b, i) => {
        switch (b.t) {
          case 'h': {
            const cls = b.level === 1 ? 'text-base font-extrabold' : b.level === 2 ? 'text-[0.95rem] font-bold' : 'text-sm font-bold'
            return <p key={i} role="heading" aria-level={b.level + 2} className={`${cls} pt-1 font-display text-ink`}>{renderInline(b.c)}</p>
          }
          case 'p': return <p key={i}>{renderInline(b.c)}</p>
          case 'ul': return <ul key={i} className="list-disc space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>
          case 'ol': return <ol key={i} start={b.start} className="list-decimal space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ol>
          case 'hr': return <hr key={i} className="border-emerald-900/10" />
          case 'table': return (
            <div key={i} className="max-w-full overflow-x-auto rounded-xl border border-emerald-900/10 bg-white">
              <table className="w-full text-left text-[13px]">
                <thead className="bg-emerald-50/70">
                  <tr>{b.head.map((c, j) => <th key={j} scope="col" className="px-3 py-1.5 font-semibold" style={{ textAlign: b.align[j] }}>{renderInline(c)}</th>)}</tr>
                </thead>
                <tbody>
                  {b.rows.map((r, j) => (
                    <tr key={j} className="border-t border-emerald-900/5">
                      {r.map((c, k) => <td key={k} className="px-3 py-1.5 tabular-nums" style={{ textAlign: b.align[k] }}>{renderInline(c)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      })}
    </div>
  )
}

