// Shared Tapis auth state for the whole app.
//
// Holds the access token + username + expiry, persisted to localStorage so the
// session survives refreshes and is visible everywhere (header, Risk Explorer).
// Auto-reverts to logged-out when the token's expiry passes.
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const TOKEN_KEY = 'subside.tapisToken'
const USER_KEY = 'subside.tapisUser'
const EXP_KEY = 'subside.tapisExp' // ms epoch

const MAX_TIMEOUT = 2_147_483_647 // setTimeout overflows past ~24.8 days

const AuthContext = createContext(null)

function clearStorage() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(EXP_KEY)
}

// Read persisted auth, dropping it if already expired.
function readStored() {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  if (!token) return { token: '', username: '', expMs: 0 }
  const expMs = Number(localStorage.getItem(EXP_KEY)) || 0
  if (expMs && Date.now() >= expMs) {
    clearStorage()
    return { token: '', username: '', expMs: 0 }
  }
  return { token, username: localStorage.getItem(USER_KEY) || '', expMs }
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(readStored)

  const logout = useCallback(() => {
    clearStorage()
    setAuth({ token: '', username: '', expMs: 0 })
  }, [])

  // `expiresAt` is the Tapis token's ISO expiry (may be undefined).
  const login = useCallback((token, username, expiresAt) => {
    let expMs = expiresAt ? Date.parse(expiresAt) : 0
    if (Number.isNaN(expMs)) expMs = 0
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, username || '')
    if (expMs) localStorage.setItem(EXP_KEY, String(expMs))
    else localStorage.removeItem(EXP_KEY)
    setAuth({ token, username: username || '', expMs })
  }, [])

  // Auto-logout exactly at expiry.
  useEffect(() => {
    if (!auth.token || !auth.expMs) return undefined
    const ms = auth.expMs - Date.now()
    if (ms <= 0) { logout(); return undefined }
    if (ms > MAX_TIMEOUT) return undefined // too far out to time; the focus check covers it
    const id = setTimeout(logout, ms)
    return () => clearTimeout(id)
  }, [auth.token, auth.expMs, logout])

  // Catch expiry that elapsed while the tab was backgrounded/asleep.
  useEffect(() => {
    if (!auth.expMs) return undefined
    const check = () => { if (Date.now() >= auth.expMs) logout() }
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => {
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
  }, [auth.expMs, logout])

  const value = {
    token: auth.token,
    username: auth.username,
    expMs: auth.expMs,
    isAuthed: !!auth.token,
    login,
    logout,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
