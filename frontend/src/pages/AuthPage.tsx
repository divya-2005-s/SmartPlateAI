import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Check, Eye, EyeOff, Lock, Mail } from 'lucide-react'
import Logo from '../components/Logo'
import ImageSlot from '../components/ImageSlot'
import { useAuth } from '../components/AuthProvider'
import { AuthApiError } from '../lib/authApi'
import { authDestination } from '../lib/authDestination'

type Mode = 'signin' | 'signup'

export default function AuthPage({ mode }: { mode: Mode }) {
  const isSignup = mode === 'signup'
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { signIn, signUp, user, loading: authLoading } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const destination = authDestination(searchParams.get('next'))

  useEffect(() => {
    if (!authLoading && user) navigate(destination, { replace: true })
  }, [authLoading, destination, navigate, user])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Use at least 8 characters for your password.')
      return
    }
    if (isSignup && password !== passwordConfirmation) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      if (isSignup) await signUp(email, password)
      else await signIn(email, password)
      navigate(destination, { replace: true })
    } catch (cause) {
      setError(cause instanceof AuthApiError ? cause.message : 'Authentication failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col px-4 py-8 sm:px-10 lg:px-16">
        <Logo />
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12">
          <h1 className="font-display text-3xl font-extrabold tracking-tight">
            {isSignup ? 'Create your account' : 'Welcome back'}
          </h1>
          <p className="mt-2 text-ink-soft">
            {isSignup ? 'Create an account to continue to SmartPlateAI.' : 'Sign in to continue to SmartPlateAI.'}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-sm font-semibold text-ink">Email</label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-soft" aria-hidden="true" />
                <input id="email" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email" required maxLength={254}
                  className="w-full rounded-xl border border-emerald-900/15 bg-white py-3 pl-11 pr-4 text-[15px] text-ink shadow-sm outline-none transition focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
              </div>
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-semibold text-ink">Password</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-soft" aria-hidden="true" />
                <input id="password" name="password" type={showPassword ? 'text' : 'password'} value={password}
                  onChange={(event) => setPassword(event.target.value)} autoComplete={isSignup ? 'new-password' : 'current-password'}
                  required minLength={8} maxLength={128}
                  className="w-full rounded-xl border border-emerald-900/15 bg-white py-3 pl-11 pr-12 text-[15px] text-ink shadow-sm outline-none transition focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
                <button type="button" onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-lg text-ink-soft hover:bg-emerald-50 hover:text-emerald-700">
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {isSignup && <p className="mt-1 text-xs text-ink-soft">Use at least 8 characters.</p>}
            </div>
            {isSignup && (
              <div>
                <label htmlFor="password-confirmation" className="mb-1.5 block text-sm font-semibold text-ink">Confirm password</label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-soft" aria-hidden="true" />
                  <input id="password-confirmation" name="password-confirmation" type={showPassword ? 'text' : 'password'}
                    value={passwordConfirmation} onChange={(event) => setPasswordConfirmation(event.target.value)}
                    autoComplete="new-password" required maxLength={128}
                    className="w-full rounded-xl border border-emerald-900/15 bg-white py-3 pl-11 pr-4 text-[15px] text-ink shadow-sm outline-none transition focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
                </div>
              </div>
            )}
            {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
            <button type="submit" disabled={submitting || authLoading}
              className="w-full rounded-full bg-emerald-600 py-3.5 text-base font-semibold text-white shadow-lg shadow-emerald-600/25 transition hover:bg-emerald-700 disabled:cursor-wait disabled:opacity-60">
              {submitting ? (isSignup ? 'Creating account…' : 'Signing in…') : (isSignup ? 'Create account' : 'Sign in')}
            </button>
          </form>

          <p className="mt-8 text-center text-sm text-ink-soft">
            {isSignup ? 'Already have an account?' : 'New to SmartPlateAI?'}{' '}
            <Link to={isSignup ? '/signin' : '/signup'} className="font-semibold text-emerald-700 hover:underline">
              {isSignup ? 'Sign in' : 'Create an account'}
            </Link>
          </p>
          <Link to="/analyze" className="mt-5 text-center text-sm font-semibold text-emerald-700 hover:underline">
            Continue to food analysis without an account
          </Link>
        </div>
      </div>

      <aside className="relative hidden overflow-hidden lg:block">
        <ImageSlot src="/images/hero.jpg" alt="A colourful, healthy plate of fresh food" eager className="absolute inset-0 h-full w-full" />
        <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-emerald-950/85 via-emerald-950/40 to-emerald-900/20" />
        <div className="relative flex h-full flex-col justify-end p-14 text-white">
          <h2 className="font-display text-3xl font-extrabold leading-tight">Understand every meal.</h2>
          <ul className="mt-6 space-y-3 text-emerald-50">
            {['Identify fresh food from a photo', 'Read packaged labels and additive codes', 'Plan meals around your preferences'].map((text) => (
              <li key={text} className="flex items-center gap-3">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-white/20">
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  )
}