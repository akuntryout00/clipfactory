import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Persona } from "@/lib/types"

const KEY = "clipfactory.activePersona"

interface PersonaCtx {
  personas: Persona[]
  isLoading: boolean
  /** id of the persona the whole UI is currently scoped to */
  activeId: string
  active: Persona | undefined
  setActiveId: (id: string) => void
}

const Ctx = createContext<PersonaCtx | null>(null)

/** Active persona = what Projects / B-roll / Generate are scoped to. Persisted in localStorage; falls back to the server default. */
export function PersonaProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useQuery({ queryKey: ["personas"], queryFn: api.personas, staleTime: 60_000 })
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: api.system, staleTime: 60_000 })
  const [stored, setStored] = useState<string>(() => localStorage.getItem(KEY) ?? "")
  const personas = useMemo(() => data ?? [], [data])
  const activeId = useMemo(() => {
    const ids = personas.map(p => p.id)
    if (stored && ids.includes(stored)) return stored
    if (sys?.default_persona && ids.includes(sys.default_persona)) return sys.default_persona
    return ids[0] ?? stored ?? ""
  }, [personas, sys, stored])
  const setActiveId = useCallback((id: string) => { localStorage.setItem(KEY, id); setStored(id) }, [])
  const value = useMemo<PersonaCtx>(() => ({
    personas, isLoading, activeId, active: personas.find(p => p.id === activeId), setActiveId,
  }), [personas, isLoading, activeId, setActiveId])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePersona(): PersonaCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error("usePersona must be used inside <PersonaProvider>")
  return c
}

export const personaLabel = (p: Persona | undefined) => (p ? p.identity?.name ?? p.name : "—")
