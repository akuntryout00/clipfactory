import { NavLink, Route, Routes, Navigate } from "react-router-dom"
import { Clapperboard, FlaskConical, Film, LayoutList, Plus, Settings2, SlidersHorizontal } from "lucide-react"
import { cn } from "@/lib/utils"
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
  { to: "/templates", label: "Templates", icon: SlidersHorizontal },
  { to: "/system", label: "System", icon: Settings2 },
]

export default function App() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-5">
        <div className="mb-8 flex items-center gap-2 px-2">
          <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground"><Clapperboard className="size-4" /></span>
          <div className="leading-tight">
            <div className="font-heading text-[15px] font-bold">Content Factory</div>
            <div className="text-[11px] text-muted-foreground">topic → template → MP4</div>
          </div>
        </div>
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
        <div className="mt-auto px-2 text-[11px] leading-relaxed text-muted-foreground">
          Persona <span className="text-foreground">Michael</span><br />1 account · 4 templates
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/generate" element={<GeneratePage />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/lab/:id" element={<LabVideoPage />} />
        </Routes>
      </main>
    </div>
  )
}
