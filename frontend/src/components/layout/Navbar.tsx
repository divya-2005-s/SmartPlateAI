import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Logo from '../Logo'
import { useAuth } from '../AuthProvider'

const links = [
  { label: 'Analyse food', to: '/analyze' },
  { label: 'Features', to: '/#features' },
  { label: 'How it works', to: '/#how-it-works' },
  { label: 'Accuracy & safety', to: '/#trust' },
]

export default function Navbar() {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const { user, loading, signOut } = useAuth()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const close = () => setOpen(false)
  const logout = async () => {
    setLogoutError(null)
    setLoggingOut(true)
    try {
      await signOut()
      close()
    } catch {
      setLogoutError('Could not sign out. Please try again.')
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-colors ${
        scrolled || open
          ? 'border-emerald-900/10 bg-cream/90 backdrop-blur-md'
          : 'border-transparent bg-cream/60 backdrop-blur-sm'
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Logo />

        <nav aria-label="Main" className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className="text-sm font-medium text-ink-soft transition-colors hover:text-emerald-700"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          {loading ? <span className="text-sm text-ink-soft">Restoring session…</span> : user ? (
            <>
              <Link to="/dashboard" className="rounded-full px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-emerald-50">Dashboard</Link>
              <span className="max-w-48 truncate text-sm text-ink-soft">{user.email}</span>
              <button type="button" onClick={logout} disabled={loggingOut}
                className="rounded-full border border-emerald-900/15 px-4 py-2 text-sm font-semibold text-ink hover:bg-emerald-50 disabled:opacity-60">
                {loggingOut ? 'Signing out…' : 'Log out'}
              </button>
            </>
          ) : (
            <>
              <Link to="/signin" className="rounded-full px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-emerald-50">Sign in</Link>
              <Link to="/signup" className="rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 hover:shadow-md">Get started</Link>
            </>
          )}
        </div>

        <button
          type="button"
          className="grid h-10 w-10 place-items-center rounded-full text-ink hover:bg-emerald-50 md:hidden"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open && (
        <div id="mobile-menu" className="border-t border-emerald-900/10 bg-cream px-4 pb-6 pt-2 md:hidden">
          <nav aria-label="Mobile" className="flex flex-col">
            {links.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                onClick={close}
                className="rounded-lg px-3 py-3 text-base font-medium text-ink hover:bg-emerald-50"
              >
                {l.label}
              </Link>
            ))}
          </nav>
          {logoutError && <p role="alert" className="mt-3 text-sm text-red-700">{logoutError}</p>}
          <div className="mt-4 grid grid-cols-2 gap-3">
            {loading ? <span className="col-span-2 py-3 text-center text-sm text-ink-soft">Restoring session…</span> : user ? (
              <>
                <span className="col-span-2 truncate py-2 text-center text-sm text-ink-soft">{user.email}</span>
                <Link to="/dashboard" onClick={close} className="col-span-2 rounded-full bg-emerald-50 py-3 text-center text-sm font-semibold text-emerald-800">Open dashboard</Link>
                <button type="button" onClick={logout} disabled={loggingOut}
                  className="col-span-2 rounded-full border border-emerald-900/15 py-3 text-sm font-semibold text-ink disabled:opacity-60">
                  {loggingOut ? 'Signing out…' : 'Log out'}
                </button>
              </>
            ) : (
              <>
                <Link to="/signin" onClick={close} className="rounded-full border border-emerald-900/15 py-3 text-center text-sm font-semibold text-ink">Sign in</Link>
                <Link to="/signup" onClick={close} className="rounded-full bg-emerald-600 py-3 text-center text-sm font-semibold text-white">Get started</Link>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  )
}