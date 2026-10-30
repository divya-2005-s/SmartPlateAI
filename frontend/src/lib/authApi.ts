import { API_BASE } from './foodApi'
import { authHeader, getSession, setSession } from './session'
import type { SessionUser } from './session'

export type AuthUser = { id: number; email: string }
export type AuthProfile = AuthUser & {
  name: string
  birth_year: number | null
  dietary_preferences: string[]
  disliked_foods: string[]
  created_at: string
}

export class AuthApiError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
    this.name = 'AuthApiError'
  }
}

async function request(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/auth/${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new AuthApiError('BACKEND_UNAVAILABLE', 'Cannot reach the SmartPlateAI server. Check that the backend is running.')
  }

  let body: Record<string, unknown> = {}
  try {
    const parsed: unknown = await response.json()
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>
  } catch {
    // An empty or malformed response is handled by the generic error below.
  }

  if (!response.ok) {
    throw new AuthApiError(
      typeof body.error_code === 'string' ? body.error_code : 'AUTH_REQUEST_FAILED',
      typeof body.message === 'string' ? body.message : 'The authentication request failed. Please try again.',
    )
  }
  return body
}

function userFrom(value: unknown): AuthUser {
  if (!value || typeof value !== 'object') throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid account response.')
  const user = value as Record<string, unknown>
  if (typeof user.id !== 'number' || typeof user.email !== 'string') {
    throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid account response.')
  }
  return { id: user.id, email: user.email }
}

async function authenticate(path: 'signup' | 'login', email: string, password: string): Promise<AuthUser> {
  const body = await request(path, { method: 'POST', body: JSON.stringify({ email, password }) })
  if (body.success !== true) throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid authentication response.')
  const user = userFrom(body.user)
  if (typeof body.token === 'string') {
    const details = body.user as Record<string, unknown>
    const sessionUser: SessionUser = {
      ...user,
      name: typeof details.name === 'string' ? details.name : user.email.split('@')[0],
      birth_year: typeof details.birth_year === 'number' ? details.birth_year : null,
      dietary_preferences: Array.isArray(details.dietary_preferences) ? details.dietary_preferences.filter((v): v is string => typeof v === 'string') : [],
      disliked_foods: Array.isArray(details.disliked_foods) ? details.disliked_foods.filter((v): v is string => typeof v === 'string') : [],
      created_at: typeof details.created_at === 'string' ? details.created_at : '',
    }
    setSession(body.token, sessionUser)
  }
  return user
}

export const signup = (email: string, password: string) => authenticate('signup', email, password)
export const login = (email: string, password: string) => authenticate('login', email, password)

export async function currentUser(): Promise<AuthUser | null> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
  } catch {
    throw new AuthApiError('BACKEND_UNAVAILABLE', 'Cannot reach the SmartPlateAI server. Check that the backend is running.')
  }
  if (response.status === 401) return null
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid session response.')
  }
  if (!response.ok) throw new AuthApiError('AUTH_REQUEST_FAILED', 'Could not restore your sign-in session.')
  return userFrom(body)
}

export async function profile(): Promise<AuthProfile> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/profile`, { credentials: 'include', headers: authHeader() })
  } catch {
    throw new AuthApiError('BACKEND_UNAVAILABLE', 'Cannot reach the SmartPlateAI server. Check that the backend is running.')
  }
  let body: Record<string, unknown> = {}
  try {
    const parsed: unknown = await response.json()
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>
  } catch {
    throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid profile response.')
  }
  const value = body.user
  if (!response.ok || !value || typeof value !== 'object') {
    throw new AuthApiError('PROFILE_REQUEST_FAILED', 'Could not load your account profile.')
  }
  const user = value as Record<string, unknown>
  if (typeof user.id !== 'number' || typeof user.email !== 'string' || typeof user.name !== 'string'
    || !Array.isArray(user.dietary_preferences) || !Array.isArray(user.disliked_foods)) {
    throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server returned an invalid account profile.')
  }
  const result: AuthProfile = {
    id: user.id,
    email: user.email,
    name: user.name,
    birth_year: typeof user.birth_year === 'number' ? user.birth_year : null,
    dietary_preferences: user.dietary_preferences.filter((v): v is string => typeof v === 'string'),
    disliked_foods: user.disliked_foods.filter((v): v is string => typeof v === 'string'),
    created_at: typeof user.created_at === 'string' ? user.created_at : '',
  }
  const token = getSession().token
  if (token) setSession(token, result)
  return result
}

export async function logout(): Promise<void> {
  const body = await request('logout', { method: 'POST' })
  if (body.success !== true) throw new AuthApiError('UNEXPECTED_RESPONSE', 'The server did not confirm sign-out.')
}