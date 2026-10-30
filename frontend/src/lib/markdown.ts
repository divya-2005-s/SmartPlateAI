/**
 * Minimal, safe Markdown parser for chatbot answers. It produces plain data (no HTML strings), which
 * components/Markdown.tsx renders as React elements, so scripts or raw HTML in an answer are always shown as text.
 * Supported: #-### headings, paragraphs, - / * / + bullet lists, 1. numbered lists, GitHub tables, --- rules,
 * **bold**, *italic*, `code`, and http(s) links.
 */
export type Inline =
  | { t: 'text'; v: string }
  | { t: 'strong'; c: Inline[] }
  | { t: 'em'; c: Inline[] }
  | { t: 'code'; v: string }
  | { t: 'link'; href: string; c: Inline[] }
export type Block =
  | { t: 'h'; level: 1 | 2 | 3; c: Inline[] }
  | { t: 'p'; c: Inline[] }
  | { t: 'ul'; items: Inline[][] }
  | { t: 'ol'; start: number; items: Inline[][] }
  | { t: 'table'; head: Inline[][]; rows: Inline[][][]; align: ('left' | 'right' | 'center')[] }
  | { t: 'hr' }

const SAFE_URL = /^https?:\/\/[^\s<>"']+$/i

export function parseInline(src: string): Inline[] {
  const out: Inline[] = []
  let i = 0
  let text = ''
  const flush = () => { if (text) { out.push({ t: 'text', v: text }); text = '' } }
  while (i < src.length) {
    const rest = src.slice(i)
    let m: RegExpMatchArray | null
    if ((m = rest.match(/^`([^`]+)`/))) { flush(); out.push({ t: 'code', v: m[1] }); i += m[0].length; continue }
    if ((m = rest.match(/^\*\*([^*][\s\S]*?)\*\*/)) || (m = rest.match(/^__([^_][\s\S]*?)__/))) {
      flush(); out.push({ t: 'strong', c: parseInline(m[1]) }); i += m[0].length; continue
    }
    if ((m = rest.match(/^\*([^*\s][^*]*?)\*/)) || (m = rest.match(/^_([^_\s][^_]*?)_(?![A-Za-z0-9])/))) {
      flush(); out.push({ t: 'em', c: parseInline(m[1]) }); i += m[0].length; continue
    }
    if ((m = rest.match(/^\[([^\]]+)\]\(([^)\s]+)\)/))) {
      flush()
      if (SAFE_URL.test(m[2])) out.push({ t: 'link', href: m[2], c: parseInline(m[1]) })
      else out.push({ t: 'text', v: m[1] })
      i += m[0].length
      continue
    }
    text += src[i]
    i += 1
  }
  flush()
  return out
}

function splitRow(line: string): string[] {
  let l = line.trim()
  if (l.startsWith('|')) l = l.slice(1)
  if (l.endsWith('|')) l = l.slice(0, -1)
  return l.split('|').map((c) => c.trim())
}

const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let para: string[] = []
  const flushPara = () => {
    if (para.length) { blocks.push({ t: 'p', c: parseInline(para.join(' ')) }); para = [] }
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()
    if (!trimmed) { flushPara(); i += 1; continue }
    if (trimmed.startsWith('```')) { // code fences are shown as plain text lines
      flushPara()
      i += 1
      const code: string[] = []
      while (i < lines.length && !lines[i].trim().startsWith('```')) { code.push(lines[i]); i += 1 }
      i += 1
      if (code.length) blocks.push({ t: 'p', c: [{ t: 'code', v: code.join('\n') }] })
      continue
    }
    const h = trimmed.match(/^(#{1,6})\s+(.*)$/)
    if (h) { flushPara(); blocks.push({ t: 'h', level: Math.min(3, h[1].length) as 1 | 2 | 3, c: parseInline(h[2].replace(/#+\s*$/, '')) }); i += 1; continue }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { flushPara(); blocks.push({ t: 'hr' }); i += 1; continue }
    if (trimmed.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flushPara()
      const head = splitRow(trimmed)
      const align = splitRow(lines[i + 1]).map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : 'left')) as ('left' | 'right' | 'center')[]
      i += 2
      const rows: Inline[][][] = []
      while (i < lines.length && lines[i].trim().includes('|') && lines[i].trim()) {
        const cells = splitRow(lines[i])
        rows.push(head.map((_, k) => parseInline(cells[k] ?? '')))
        i += 1
      }
      blocks.push({ t: 'table', head: head.map(parseInline), rows, align: head.map((_, k) => align[k] ?? 'left') })
      continue
    }
    const ul = trimmed.match(/^[-*+]\s+(.*)$/)
    const ol = trimmed.match(/^(\d{1,3})[.)]\s+(.*)$/)
    if (ul || ol) {
      flushPara()
      const items: Inline[][] = []
      const start = ol ? Number(ol[1]) : 1
      while (i < lines.length) {
        const t = lines[i].trim()
        const m = ul ? t.match(/^[-*+]\s+(.*)$/) : t.match(/^\d{1,3}[.)]\s+(.*)$/)
        if (m) { items.push(parseInline(m[1])); i += 1; continue }
        if (t && /^\s{2,}/.test(lines[i]) && items.length) { // indented continuation line
          items[items.length - 1] = [...items[items.length - 1], { t: 'text', v: ' ' }, ...parseInline(t)]
          i += 1
          continue
        }
        break
      }
      blocks.push(ul ? { t: 'ul', items } : { t: 'ol', start, items })
      continue
    }
    para.push(trimmed)
    i += 1
  }
  flushPara()
  return blocks
}
