import type { ReactNode } from 'react'
import { CircleAlert, Inbox, RefreshCw } from 'lucide-react'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-ink-soft">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

export function Card({ children, className = '', title, action }: { children: ReactNode; className?: string; title?: string; action?: ReactNode }) {
  return (
    <section className={`rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="font-display text-lg font-extrabold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-4 text-ink-soft">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
      {label}
    </div>
  )
}

export function ErrorBox({ message, code, onRetry }: { message: string; code?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">
      <CircleAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{message}</p>
        {code && <p className="text-xs opacity-75">Code: {code}</p>}
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 rounded-full bg-white px-4 py-1.5 text-sm font-semibold ring-1 ring-red-200 hover:bg-red-100">
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retry
        </button>
      )}
    </div>
  )
}

export function Empty({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-emerald-900/15 px-6 py-10 text-center">
      <Inbox className="h-8 w-8 text-emerald-600/70" aria-hidden="true" />
      <p className="font-semibold">{title}</p>
      {text && <p className="max-w-md text-sm text-ink-soft">{text}</p>}
      {action}
    </div>
  )
}

export function Badge({ children, tone = 'green' }: { children: ReactNode; tone?: 'green' | 'amber' | 'red' | 'grey' | 'blue' }) {
  const t = {
    green: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20',
    amber: 'bg-amber-50 text-amber-900 ring-amber-600/25',
    red: 'bg-red-50 text-red-800 ring-red-600/20',
    grey: 'bg-slate-100 text-slate-700 ring-slate-500/20',
    blue: 'bg-sky-50 text-sky-800 ring-sky-600/20',
  }[tone]
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${t}`}>{children}</span>
}

export const btn = {
  primary: 'inline-flex items-center justify-center gap-2 rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50',
  secondary: 'inline-flex items-center justify-center gap-2 rounded-full border border-emerald-900/15 bg-white px-5 py-2.5 text-sm font-semibold text-ink hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50',
  danger: 'inline-flex items-center justify-center gap-2 rounded-full border border-red-200 bg-white px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50',
  ghost: 'inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-50',
}
export const input = 'w-full rounded-xl border border-emerald-900/15 bg-white px-4 py-2.5 text-sm outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15'
export const label = 'mb-1.5 block text-sm font-semibold'

export const fmt = (v: number | null | undefined, unit = '') =>
  v === null || v === undefined ? 'Not available' : `${Math.round(v * 100) / 100}${unit ? ' ' + unit : ''}`

export function todayISO(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
