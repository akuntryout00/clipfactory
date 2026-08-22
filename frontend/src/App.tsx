import { NavLink, Route, Routes, Navigate, useLocation } from "react-router-dom"
import { Clapperboard, FlaskConical, Film, KeyRound, LayoutList, Plus, Settings2, SlidersHorizontal, UserRound } from "lucide-react"
import { cn } from "@/lib/utils"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { PersonaProvider, personaLabel, usePersona } from "@/lib/persona"
import PersonasPage from "@/pages/PersonasPage"
import SetupPage from "@/pages/SetupPage"
import ProjectsPage from "@/pages/ProjectsPage"
import GeneratePage from "@/pages/GeneratePage"
import ProjectPage from "@/pages/ProjectPage"
import AssetsPage from "@/pages/AssetsPage"
import TemplatesPage from "@/pages/TemplatesPage"
import SystemPage from "@/pages/SystemPage"
import LabPage from "@/pages/LabPage"
import LabVideoPage from "@/pages/LabVideoPage"

const nav = [
  { to: "/projects", label: "Projects", icon: LayoutList },
  { to: "/generate", label: "Generate", icon: Plus },
  { to: "/assets", label: "B-roll", icon: Film },
  { to: "/personas", label: "Personas", icon: UserRound },
  { to: "/templates", label: "Templates", icon: SlidersHorizontal },
  { to: "/system", label: "System", icon: Settings2 },
  { to: "/setup", label: "Settings", icon: KeyRound },
]

/** Scopes Projects, Generate and B-roll to one persona. */
function PersonaSwitcher() {
  const { personas, activeId, active, setActiveId } = usePersona()
  return (
    <div className="mb-5 rounded-md border border-sidebar-border bg-background/40 p-2">
      <label htmlFor="persona-switch" className="mb-1 block px-0.5 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Persona</label>
      <select id="persona-switch" value={activeId} onChange={e => setActiveId(e.target.value)}
        className="h-8 w-full rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
        {personas.length === 0 && <option value="">Loading…</option>}
        {personas.map(p => <option key={p.id} value={p.id}>{personaLabel(p)}</option>)}
      </select>
      {active && <p className="mt-1 truncate px-0.5 text-[11px] text-muted-foreground" title={active.name}>{active.name}</p>}
    </div>
  )
}

function SidebarFooter() {
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: api.templates, staleTime: 60_000 })
  const { personas } = usePersona()
  return (
    <div className="mt-auto px-2 text-[11px] leading-relaxed text-muted-foreground">
      {personas.length} personas · {templates?.length ?? 0} templates<br />no auto-posting
    </div>
  )
}

export default function App() {
  return (
    <PersonaProvider>
      <Shell />
    </PersonaProvider>
  )
}

/** First run: until the required providers are configured, every page redirects to Setup (System stays reachable). */
function SetupGuard({ children }: { children: React.ReactNode }) {
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: api.system, staleTime: 15_000 })
  const loc = useLocation()
  if (sys?.setup_required && loc.pathname !== "/setup" && loc.pathname !== "/system") return <Navigate to="/setup" replace />
  return <>{children}</>
}

function Shell() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-5">
        <div className="mb-8 flex items-center gap-2 px-2">
          <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground"><Clapperboard className="size-4" /></span>
          <div className="leading-tight">
            <div className="font-heading text-[15px] font-bold">ClipFactory</div>
            <div className="text-[11px] text-muted-foreground">topic → template → MP4</div>
          </div>
        </div>
        <PersonaSwitcher />
        <nav className="flex flex-col gap-1">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-2 focus-visible:outline-ring",
              isActive && "bg-sidebar-accent text-sidebar-accent-foreground font-medium")}>
              <Icon className="size-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 border-t border-sidebar-border pt-4">
          <div className="mb-1 px-2.5 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Separate module</div>
          <NavLink to="/lab" className={({ isActive }) => cn(
            "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-2 focus-visible:outline-ring",
            isActive && "bg-sidebar-accent text-sidebar-accent-foreground font-medium")}>
            <FlaskConical className="size-4" /> AI Lab
          </NavLink>
        </div>
        <SidebarFooter />
      </aside>
      <main className="min-w-0 flex-1">
        <SetupGuard>
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/generate" element={<GeneratePage />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/personas" element={<PersonasPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/lab/:id" element={<LabVideoPage />} />
          <Route path="/setup" element={<SetupPage />} />
        </Routes>
        </SetupGuard>
      </main>
    </div>
  )
}
