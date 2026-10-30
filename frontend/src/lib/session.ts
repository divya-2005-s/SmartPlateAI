/** Signed-in session: token + user, kept in memory and (best effort) in localStorage. No imports, to avoid cycles. */
export type SessionUser = {
  id: number
  email: string
  name: string
  birth_year: number | null
  dietary_preferences: string[]
  disliked_foods: string[]
  created_at: string
}
type State = { token: string | null; user: SessionUser | null }

const KEY = 'smartplate.session'
let state: State = load()
const listeners = new Set<() => void>()

function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as State
      if (parsed && typeof parsed.token === 'string') return parsed
    }
  } catch {
    /* storage unavailable */
  }
  return { token: null, user: null }
}

function persist() {
  try {
    if (state.token) localStorage.setItem(KEY, JSON.stringify(state))
    else localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: session lasts for this tab only */
  }
}

export function getSession(): State {
  return state
}
export function getToken(): string | null {
  return state.token
}
export function setSession(token: string | null, user: SessionUser | null) {
  state = { token, user }
  persist()
  listeners.forEach((l) => l())
}
export function setUser(user: SessionUser) {
  state = { ...state, user }
  persist()
  listeners.forEach((l) => l())
}
export function subscribe(l: () => void): () => void {
  listeners.add(l)
  return () => listeners.delete(l)
}
export function authHeader(): Record<string, string> {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {}
}
