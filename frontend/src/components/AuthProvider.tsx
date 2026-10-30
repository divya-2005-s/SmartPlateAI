import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { currentUser, login as loginRequest, profile, signup as signupRequest } from '../lib/authApi'
import type { AuthUser } from '../lib/authApi'
import { getSession, setSession, setUser as setStoredUser } from '../lib/session'
import type { SessionUser } from '../lib/session'
import { refreshMe, signOut as signOutRequest } from '../lib/api'

type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  signUp: (email: string, password: string) => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    currentUser()
      .then(async (restored) => {
        if (!active) return
        if (restored) {
          await publishUser(restored, setUser)
          return
        }
        await refreshMe()
        const legacyUser = getSession().user
        if (active && legacyUser) setUser({ id: legacyUser.id, email: legacyUser.email })
      })
      .catch(() => { if (active) setUser(null) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const signUp = async (email: string, password: string) => {
    await publishUser(await signupRequest(email, password), setUser)
  }
  const signIn = async (email: string, password: string) => {
    await publishUser(await loginRequest(email, password), setUser)
  }
  const signOut = async () => {
    await signOutRequest()
    setUser(null)
    setSession(null, null)
  }

  async function publishUser(user: AuthUser, update: (value: AuthUser | null) => void) {
    update(user)
    let sessionUser: SessionUser
    try {
      sessionUser = await profile()
    } catch {
      sessionUser = {
        ...user,
        name: user.email.split('@')[0] || user.email,
        birth_year: null,
        dietary_preferences: [],
        disliked_foods: [],
        created_at: '',
      }
    }
    setSession(getSession().token, sessionUser)
    setStoredUser(sessionUser)
  }

  return <AuthContext.Provider value={{ user, loading, signUp, signIn, signOut }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}