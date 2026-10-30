import { useSyncExternalStore } from 'react'
import type { AnalysisContext } from './chatApi'

/** The most recent analysis (fresh or packaged), shared between the Analyse page and the Chatbot page. */
let current: AnalysisContext | null = null
const listeners = new Set<() => void>()

export function setCurrentAnalysis(ctx: AnalysisContext | null) {
  current = ctx
  listeners.forEach((l) => l())
}
export function getCurrentAnalysis() {
  return current
}
export function useCurrentAnalysis() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => current,
    () => current,
  )
}
