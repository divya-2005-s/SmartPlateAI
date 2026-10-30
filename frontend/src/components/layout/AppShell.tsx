import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, Apple, ChartColumn, Bot, Calculator, ClipboardList, FileText, FlaskConical, Clock, LayoutDashboard, LogIn, LogOut, Menu,
  Package, Scale, ShieldAlert, User, X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Logo from '../Logo'
import { useSession } from '../../lib/api'
import { useAuth } from '../AuthProvider'

type Item = { to: string; label: string; icon: LucideIcon; auth?: boolean }
const NAV: { group: string; items: Item[] }[] = [
  { group: 'Overview', items: [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, auth: true }] },
  {
    group: 'Analyse',
    items: [
      { to: '/analyze', label: 'Analyze food', icon: Apple },
      { to: '/scan-packaged', label: 'Packaged food scanner', icon: Package },
      { to: '/chemical', label: 'Chemical intelligence', icon: FlaskConical },
      { to: '/compare', label: 'Product comparison', icon: Scale },
      { to: '/chat', label: 'AI chatbot', icon: Bot },
    ],
  },
  {
    group: 'My data',
    items: [
      { to: '/history', label: 'Scan history', icon: Clock, auth: true },
      { to: '/nutrition', label: 'Daily nutrition', icon: ChartColumn, auth: true },
      { to: '/meal-planner', label: 'Meal planner', icon: ClipboardList, auth: true },
      { to: '/allergens', label: 'Allergen preferences', icon: ShieldAlert, auth: true },
      { to: '/reports', label: 'Reports', icon: FileText, auth: true },
    ],
  },
  {
    group: 'Tools',
    items: [
      { to: '/bmi', label: 'BMI calculator', icon: Calculator },
      { to: '/profile', label: 'Profile & settings', icon: User, auth: true },
    ],
  },
]

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <p role="status" className="p-8 text-center text-sm text-ink-soft">Restoring session…</p>
  if (!user) return <Navigate to={`/signin?next=${encodeURIComponent(loc.pathname)}`} replace />
  return <>{children}</>
}

export default function AppShell() {
  const { user } = useSession()
  const { signOut: logOut } = useAuth()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const navigate = useNavigate()
  useEffect(() => setOpen(false), [loc.pathname])
  const nav = (
    <nav aria-label="App" className="flex flex-col gap-5">
      {NAV.map((g) => (
        <div key={g.group}>
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-soft/80">{g.group}</p>
          <ul className="space-y-0.5">
            {g.items.map(({ to, label, icon: Icon, auth }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${
                      isActive ? 'bg-emerald-600 text-white shadow-sm' : 'text-ink hover:bg-emerald-50'
                    }`
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span className="flex-1">{label}</span>
                  {auth && !user && <span className="text-[10px] font-semibold opacity-60">sign in</span>}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )

  const account = user ? (
    <div className="rounded-2xl bg-emerald-50/70 p-3">
      <p className="truncate text-sm font-semibold">{user?.name ?? 'Signed in'}</p>
      <p className="truncate text-xs text-ink-soft">{user?.email}</p>
      <button type="button" onClick={() => { void logOut().then(() => navigate('/')) }}
        className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 hover:underline">
        <LogOut className="h-3.5 w-3.5" aria-hidden="true" /> Sign out
      </button>
    </div>
  ) : (
    <Link to="/signin" className="flex items-center justify-center gap-2 rounded-full bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700">
      <LogIn className="h-4 w-4" aria-hidden="true" /> Sign in
    </Link>
  )

  return (
    <div className="min-h-screen bg-cream text-ink lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-screen flex-col gap-6 overflow-y-auto border-r border-emerald-900/10 bg-white/70 p-4 lg:flex">
        <div className="px-2 pt-1"><Logo /></div>
        <div className="flex-1">{nav}</div>
        {account}
      </aside>

      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-emerald-900/10 bg-cream/90 px-4 backdrop-blur-md lg:hidden">
        <Logo />
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="mobile-nav"
          aria-label={open ? 'Close menu' : 'Open menu'} className="grid h-10 w-10 place-items-center rounded-full hover:bg-emerald-50">
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </header>
      {open && (
        <div id="mobile-nav" className="fixed inset-x-0 top-14 z-30 max-h-[calc(100vh-3.5rem)] overflow-y-auto border-b border-emerald-900/10 bg-cream p-4 shadow-lift lg:hidden">
          {nav}
          <div className="mt-4">{account}</div>
        </div>
      )}

      <main className="min-w-0 px-4 pb-16 pt-6 sm:px-6 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
        <p className="mx-auto mt-12 flex max-w-6xl items-center gap-2 text-xs text-ink-soft">
          <Activity className="h-3.5 w-3.5" aria-hidden="true" /> SmartPlateAI gives general information, not medical advice. Values show their source.
        </p>
      </main>
    </div>
  )
}
